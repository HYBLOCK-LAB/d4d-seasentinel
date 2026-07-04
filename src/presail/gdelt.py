from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

import httpx

from presail.cache import cache_key, get_or_fetch
from presail.paths import data_dir

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
CHUNK_DAYS = 365
MIN_INTERVAL = 6.0
BACKOFF_SECONDS = 30.0
MAX_RETRIES = 8

_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _request(query: str, mode: str, start: str, end: str) -> dict:
    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "startdatetime": start,
        "enddatetime": end,
    }
    for attempt in range(MAX_RETRIES):
        _throttle()
        resp = httpx.get(BASE, params=params, timeout=60.0)
        body = resp.text.strip()
        if resp.status_code == 429 or body.startswith("Please limit"):
            time.sleep(BACKOFF_SECONDS)
            continue
        resp.raise_for_status()
        if not body:
            return {"timeline": []}
        return json.loads(body)
    raise RuntimeError(f"GDELT rate-limited after {MAX_RETRIES} retries: {query!r}")


def _parse_date(raw: str) -> date:
    text = raw.replace("Z", "").replace("-", "").replace(":", "")
    return datetime.strptime(text[:8], "%Y%m%d").date()


def _points(payload: dict) -> dict[date, dict]:
    out: dict[date, dict] = {}
    for series in payload.get("timeline", []):
        for point in series.get("data", []):
            day = _parse_date(point["date"])
            out[day] = point
    return out


def _chunks(start: date, end: date):
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=CHUNK_DAYS), end)
        yield cursor, stop
        cursor = stop


def _stamp(day: date) -> str:
    return day.strftime("%Y%m%d%H%M%S")


def _fetch_mode(query: str, mode: str, start: date, end: date) -> dict[date, dict]:
    merged: dict[date, dict] = {}
    for chunk_start, chunk_end in _chunks(start, end):
        key = cache_key(query, mode, _stamp(chunk_start), _stamp(chunk_end))
        path = data_dir("raw", "gdelt", f"{key}.json")
        payload = get_or_fetch(
            path,
            lambda: _request(query, mode, _stamp(chunk_start), _stamp(chunk_end)),
        )
        merged.update(_points(payload))
    return merged


def fetch_volraw_and_tone(query: str, start: date, end: date, include_tone: bool = True) -> list[dict]:
    volraw = _fetch_mode(query, "timelinevolraw", start, end)
    tone = _fetch_mode(query, "timelinetone", start, end) if include_tone else {}
    days = sorted(set(volraw) | set(tone))
    rows = []
    for day in days:
        vr = volraw.get(day, {})
        tn = tone.get(day, {})
        rows.append(
            {
                "date": day.isoformat(),
                "article_count": float(vr.get("value", 0.0)),
                "monitored_volume": float(vr.get("norm", 0.0)),
                "tone": float(tn.get("value", 0.0)) if tn else None,
            }
        )
    return rows
