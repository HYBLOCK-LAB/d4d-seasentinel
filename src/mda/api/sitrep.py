import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter

from mda.api import queries
from mda.api.assess import apply_assessments
from mda.api.llm import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from mda.store import pg

REPORT_INTERVAL = timedelta(minutes=60)
MIN_INTERVAL = timedelta(minutes=5)

SYSTEM_PROMPT = (
    "당신은 대한민국 해양영역인식(MDA) 상황실의 상황장교입니다. "
    "제공된 위협 목록과 OSINT 항목만을 근거로 3~6문장의 한국어 상황보고(SITREP)를 작성하세요. "
    "우선순위가 높은 위협부터 다루고, 근거가 된 위협 제목을 인용하세요. "
    "제공된 데이터에 없는 사실을 지어내지 마세요. 특이사항이 없으면 '특이사항 없음'으로 시작하세요. "
    "과장·미사여구 금지. 보고 본문만 출력하세요."
)

router = APIRouter()
_locks: dict[str, asyncio.Lock] = {}


def threat_signature(threats: list[dict]) -> str:
    keys = sorted(f"{t['id']}:{t['level']}" for t in threats)
    return hashlib.sha1("|".join(keys).encode()).hexdigest()


def should_generate(
    prev_at: datetime | None,
    prev_sig: str | None,
    cur_sig: str,
    now: datetime,
) -> bool:
    if prev_at is None:
        return True
    age = now - prev_at
    if age >= REPORT_INTERVAL:
        return True
    return cur_sig != prev_sig and age >= MIN_INTERVAL


def _latest(conn, region_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "select generated_at, threat_sig, body_ko, model from sitrep "
            "where region_id = %s order by generated_at desc limit 1",
            (region_id,),
        )
        return cur.fetchone()


def _stored(prev, stale: bool) -> dict:
    generated_at, threat_sig, body_ko, model = prev
    return {
        "body_ko": body_ko,
        "generated_at": generated_at.isoformat(),
        "model": model,
        "threat_sig": threat_sig,
        "stale": stale,
    }


async def _generate(region_id: str, start: datetime, end: datetime, threats: list, osint: list) -> str:
    user_content = json.dumps(
        {
            "region": region_id,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "now": datetime.now(timezone.utc).isoformat(),
            "threats": [
                {
                    "id": t["id"],
                    "type": t["type"],
                    "level": t["level"],
                    "score": t["score"],
                    "title_ko": t["title_ko"],
                }
                for t in threats[:10]
            ],
            "osint": [
                {"ts": o["ts"], "kind": o["kind"], "text": (o["text"] or "")[:150]}
                for o in osint
            ],
        },
        ensure_ascii=False,
    )
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": 600,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers
        )
        response.raise_for_status()
        data = response.json()
    body = (data["choices"][0]["message"]["content"] or "").strip()
    if not body:
        raise ValueError("empty sitrep body")
    return body


@router.get("/sitrep")
async def get_sitrep(region: str | None = None) -> dict:
    region_obj = queries.resolve_region(region)
    lock = _locks.setdefault(region_obj.region_id, asyncio.Lock())
    async with lock:
        with pg.connect() as conn:
            apply_assessments(conn)
            start, end = queries.compute_window(conn)
            threats = queries.get_threats(conn, region_obj, start, end)
            cur_sig = threat_signature(threats)
            prev = _latest(conn, region_obj.region_id)
            now = datetime.now(timezone.utc)
            if prev is not None and not should_generate(prev[0], prev[1], cur_sig, now):
                return _stored(prev, stale=False)
            osint = queries.get_osint(conn, region_obj, start, end)["items"][:10]

        try:
            body = await _generate(region_obj.region_id, start, end, threats, osint)
        except Exception:
            if prev is not None:
                return _stored(prev, stale=True)
            return {
                "body_ko": None,
                "generated_at": None,
                "model": None,
                "threat_sig": cur_sig,
                "stale": True,
            }

        with pg.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "insert into sitrep (region_id, model, threat_sig, body_ko) "
                    "values (%s, %s, %s, %s) returning generated_at",
                    (region_obj.region_id, LLM_MODEL, cur_sig, body),
                )
                generated_at = cur.fetchone()[0]
    return {
        "body_ko": body,
        "generated_at": generated_at.isoformat(),
        "model": LLM_MODEL,
        "threat_sig": cur_sig,
        "stale": False,
    }
