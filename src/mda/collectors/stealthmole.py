from __future__ import annotations

import html
import os
import re
import time
import uuid
from datetime import datetime, timezone

import httpx
import jwt
import yaml
from dotenv import load_dotenv

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    text = raw.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    text = _TAG_RE.sub("", text)
    return html.unescape(text).strip()

from mda.paths import config_path, repo_root
from mda.store import pg

DEFAULT_BASE = "https://hackathon.stealthmole.com"
POLL_LIMIT = 100
MAX_POLL_PAGES = 3
SAFETY_FLOOR = 2
MIN_INTERVAL = 2.5
BACKOFF_SECONDS = 12.0
MAX_RETRIES = 4

_env_loaded = False
_last_call = 0.0


class QuotaExceeded(RuntimeError):
    pass


class Throttled(RuntimeError):
    pass


def _env() -> tuple[str, str, str]:
    global _env_loaded
    if not _env_loaded:
        load_dotenv(repo_root() / ".env")
        _env_loaded = True
    access = os.environ.get("STEALTHMOLE_ACCESS_KEY")
    secret = os.environ.get("STEALTHMOLE_SECRET_KEY")
    base = os.environ.get("STEALTHMOLE_BASE_URL") or DEFAULT_BASE
    if not access or not secret:
        raise RuntimeError("STEALTHMOLE_ACCESS_KEY / STEALTHMOLE_SECRET_KEY not set")
    return access, secret, base


def _token() -> str:
    access, secret, _ = _env()
    payload = {"access_key": access, "nonce": uuid.uuid4().hex, "iat": int(time.time())}
    return jwt.encode(payload, secret, algorithm="HS256")


def _throttle() -> None:
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _get(path: str, params: dict | None = None) -> httpx.Response:
    _, _, base = _env()
    resp = None
    for _ in range(MAX_RETRIES):
        _throttle()
        resp = httpx.get(
            f"{base}{path}",
            params=params or {},
            headers={"Authorization": f"Bearer {_token()}"},
            timeout=60.0,
        )
        if resp.status_code == 429:
            time.sleep(BACKOFF_SECONDS)
            continue
        return resp
    raise Throttled(f"429 after {MAX_RETRIES} tries for {path}")


def quotas() -> dict:
    resp = _get("/user/quotas")
    resp.raise_for_status()
    return resp.json()


def _items_from(payload: dict) -> tuple[list[dict], str | None, bool]:
    data = payload.get("data", []) or []
    return data, payload.get("id"), bool(payload.get("last", True))


def _search_keyword(term: str, targets: list[str]) -> list[dict]:
    resp = _get(
        "/tt/search/keyword/target",
        {"targets": ",".join(targets), "text": term, "limit": POLL_LIMIT, "wait": "false"},
    )
    if resp.status_code == 426:
        raise QuotaExceeded()
    resp.raise_for_status()
    by_target = resp.json()
    collected: list[dict] = []
    for target, status in by_target.items():
        if not isinstance(status, dict):
            continue
        data, cache_id, last = _items_from(status)
        collected.extend((target, item) for item in data)
        pages = 0
        while not last and cache_id and pages < MAX_POLL_PAGES:
            poll = _get(f"/tt/search/{cache_id}", {"limit": POLL_LIMIT})
            if poll.status_code in (202, 408):
                if poll.status_code == 408:
                    break
                time.sleep(2.0)
                continue
            poll.raise_for_status()
            payload = poll.json()
            data, cache_id, last = _items_from(payload)
            collected.extend((target, item) for item in data)
            pages += 1
    return collected


def _to_ts(create_date) -> datetime:
    try:
        return datetime.fromtimestamp(int(create_date), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _rows(term: str, lang: str, category: str, target: str, item: dict) -> tuple[dict, dict]:
    node_id = str(item.get("id") or uuid.uuid4().hex)
    highlight = item.get("highlight")
    text = _strip_html(highlight) if highlight else (item.get("value") or "")
    ts = _to_ts(item.get("createDate"))
    item_id = f"stealthmole:tt:{target}:{node_id}"
    osint = {
        "item_id": item_id,
        "ts": ts,
        "region_id": None,
        "kind": category,
        "lang": lang,
        "source_module": "stealthmole_tt",
        "text": text[:4000],
        "sentiment": None,
        "weight": None,
        "source_id": "stealthmole",
        "collector": "stealthmole_tt",
        "raw_ref": f"term={term}",
    }
    document = {
        "document_id": item_id,
        "doc_type": target,
        "title": text[:200],
        "lang": lang,
        "url": None,
        "published_at": ts,
        "text_excerpt": text[:2000],
        "sha256": None,
        "region_id": None,
        "source_id": "stealthmole",
        "collector": "stealthmole_tt",
        "raw_ref": f"term={term}",
    }
    return osint, document


def collect(max_items: int | None = None) -> dict:
    spec = yaml.safe_load(config_path("stealthmole_keywords.yaml").open())
    targets = spec["targets"]
    keywords = spec["keywords"]
    quota = quotas().get("TT", {})
    budget = quota.get("allowed", 0) - quota.get("used", 0) - SAFETY_FLOOR

    osint_rows: list[dict] = []
    doc_rows: dict[str, dict] = {}
    calls = 0
    for kw in keywords:
        if budget is not None and calls >= budget:
            break
        try:
            items = _search_keyword(kw["term"], targets)
        except QuotaExceeded:
            break
        except Throttled:
            continue
        calls += 1
        for target, item in items:
            osint, document = _rows(kw["term"], kw.get("lang", ""), kw.get("category", ""), target, item)
            osint_rows.append(osint)
            doc_rows[document["document_id"]] = document
        if max_items and len(osint_rows) >= max_items:
            break

    seen = set()
    deduped = []
    for row in osint_rows:
        if row["item_id"] in seen:
            continue
        seen.add(row["item_id"])
        deduped.append(row)

    with pg.connect() as conn:
        pg.upsert(conn, "document", list(doc_rows.values()), conflict=["document_id"], update=["title", "text_excerpt", "published_at"])
        pg.upsert(conn, "osint_item", deduped, conflict=["item_id"], update=["text", "ts", "kind"])
    return {"keywords_run": calls, "osint_items": len(deduped), "documents": len(doc_rows), "tt_budget": budget}
