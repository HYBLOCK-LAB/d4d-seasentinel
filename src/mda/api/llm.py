import hashlib
import json
import os
from datetime import datetime

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mda.api import datasets, queries
from mda.paths import repo_root

load_dotenv(repo_root() / ".env")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-5.4")

SYSTEM_PROMPT = """당신은 대한민국 해양영역인식(MDA) 지휘결심 지원 분석관입니다.
'SEASENTINEL' 시스템이 제공하는 실시간 상황 컨텍스트(위협 경보·선박·OSINT·현재 시각)를 근거로만 답하세요.

규칙:
- 반드시 한국어로, 지휘관이 즉시 활용할 수 있게 간결하고 구조적으로 답하세요.
- 제공된 컨텍스트에 근거해 답하고, 근거가 된 항목(선박명·경보·OSINT 출처)을 함께 인용하세요.
- 컨텍스트에 없는 사실은 지어내지 마세요. 불확실하면 불확실하다고 명시하세요.
- 필요 시 권고 조치를 제시하세요: 관심표적 지정 / ISR 재촬영 / 경비함 유도·차단 / 채증 패키지 / 지휘보고.
- 4~8문장 또는 짧은 불릿으로. 과장·미사여구 금지."""

AGENT_SUFFIX = (
    "\n\n당신은 도구로 온톨로지 데이터를 조회·조정하고 화면을 조작할 수 있습니다. 능력은 4가지입니다.\n"
    "1) 데이터 조회: 위협·선박·OSINT·활동량 질의에는 반드시 get_threats/get_threat_evidence/get_osint/get_timeline로"
    " 실데이터를 확인한 뒤 항목(위협 제목·점수·OSINT 출처)을 인용해 답하세요. 조회 없이 수치나 현황을 단정하지 마세요.\n"
    "2) 위협 비교: 비교 대상 각각에 get_threat_evidence를 호출해 근거 term과 점수 구성을 대조하고,"
    " 우선순위 판단의 근거를 명시하세요.\n"
    "3) 지도 조작: 화면 이동·레이어·선택 요청에는 set_region/set_time_window/toggle_layer/focus_map/select_threat를"
    " 호출하세요. threat_id와 좌표는 조회 결과에 존재하는 실제 값만 사용하세요.\n"
    "4) 확인 보고 반영: 분석관이 현장 확인 결과(위협 아님, 위험 상향 등)를 보고하면 assess_threat로 조정 인자를"
    " 기록하세요. 대상이 불명확하면 컨텍스트의 selected_threat를 우선 사용하고, 없으면 get_threats로 특정한 뒤"
    " 어느 위협을 조정했는지와 변경된 score/level을 답변에 보고하세요.\n"
    "존재하지 않는 id를 지어내지 마세요. 도구 실행 결과는 시스템이 화면에 자동 반영합니다."
)

DIGEST_SYSTEM_PROMPT = (
    "당신은 해양 OSINT 분석관입니다. 아래 텔레그램/다크웹 수집 원문들에서 "
    "'해상 영역 인식에 유의미한 정보'만 추출해 한국어로 항목화하세요. "
    "원문에 없는 사실을 만들지 마세요. 반드시 JSON만 출력하세요. "
    'schema: {"items":[{"category":"militia_movement|port_logistics|sanctions_evasion|infra_threat|other",'
    '"summary_ko":"1-2문장 요약","time_hint":"원문상 시점","area_hint":"해역/항만 등 지리 힌트",'
    '"severity":1-5,"evidence_ids":["원문 id"]}]}. 유의미한 항목이 없으면 빈 배열.'
)

JUNK_MODEL_IDS = {"high", "low", "medium", "gemini", "gpt", "chat_20706", "chat_23310"}

router = APIRouter()

_digest_cache: dict[str, dict] = {}


class CopilotRequest(BaseModel):
    query: str
    context: str = ""
    model: str | None = None


class AgentRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    tools: list[dict] | None = None


class DigestRequest(BaseModel):
    region: str | None = None
    start: str | None = None
    end: str | None = None
    model: str | None = None
    dataset: str | None = None


@router.post("/copilot")
async def copilot(request: CopilotRequest) -> StreamingResponse:
    model = request.model or LLM_MODEL
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"[현재 상황 컨텍스트]\n{request.context}\n\n[지휘관 질의]\n{request.query}",
        },
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 800,
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}

    async def relay():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{LLM_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(relay(), media_type="text/event-stream")


@router.get("/models")
async def models() -> dict:
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{LLM_BASE_URL}/models", headers=headers)
            response.raise_for_status()
            data = response.json()
        ids = sorted(
            {
                m["id"]
                for m in data.get("data", [])
                if "/" not in m["id"]
                and m["id"] not in JUNK_MODEL_IDS
                and any(c.isdigit() for c in m["id"])
            }
        )
    except Exception:
        ids = []
    return {"models": ids or [LLM_MODEL], "default": LLM_MODEL}


@router.post("/copilot/agent")
async def copilot_agent(request: AgentRequest) -> dict:
    payload = {
        "model": request.model or LLM_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT + AGENT_SUFFIX}] + request.messages,
        "temperature": 0.3,
        "max_tokens": 900,
    }
    if request.tools:
        payload["tools"] = request.tools
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"message": data["choices"][0]["message"]}


@router.post("/osint/digest")
async def osint_digest(request: DigestRequest) -> dict:
    region = queries.resolve_region(request.region)
    with datasets.dataset_conn(request.dataset) as conn:
        if request.start and request.end:
            start = datetime.fromisoformat(request.start)
            end = datetime.fromisoformat(request.end)
        else:
            start, end = queries.compute_window(
                conn, extend_to_now=datasets.is_live(request.dataset)
            )
        items = queries.get_osint(conn, region, start, end)["items"][:80]

    user_content = json.dumps(
        [
            {"id": item["id"], "ts": item["ts"], "kind": item["kind"], "text": (item["text"] or "")[:400]}
            for item in items
        ],
        ensure_ascii=False,
    )
    used_model = request.model or LLM_MODEL
    cache_key = hashlib.sha1(f"{used_model}\n{user_content}".encode()).hexdigest()
    cached = _digest_cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}
    payload = {
        "model": used_model,
        "messages": [
            {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": 1600,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    content = data["choices"][0]["message"]["content"]

    valid_ids = {item["id"] for item in items}
    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        parsed = json.loads(text[start_idx : end_idx + 1])
        parsed_items = []
        for entry in parsed.get("items", []):
            entry["evidence_ids"] = [eid for eid in entry.get("evidence_ids", []) if eid in valid_ids]
            parsed_items.append(entry)
    except Exception:
        return {"items": [], "error": "parse"}

    result = {
        "items": parsed_items,
        "model": used_model,
        "note": "LLM 생성 분석 — 근거 원문 확인 필수",
        "input_count": len(items),
    }
    if len(_digest_cache) > 64:
        _digest_cache.clear()
    _digest_cache[cache_key] = result
    return result
