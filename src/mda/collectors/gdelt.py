from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta

import httpx

from mda.paths import data_dir
from mda.store.cache import cache_key, get_or_fetch

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
CHUNK_DAYS = 365
MIN_INTERVAL = 8.0
BACKOFF_SECONDS = 45.0
MAX_RETRIES = 4

_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


class GdeltThrottled(RuntimeError):
    pass


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
        throttled = resp.status_code == 429 or "limit requests" in body[:80].lower()
        if throttled:
            time.sleep(BACKOFF_SECONDS)
            continue
        resp.raise_for_status()
        if not body or not body.startswith("{"):
            time.sleep(BACKOFF_SECONDS)
            continue
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            time.sleep(BACKOFF_SECONDS)
    raise GdeltThrottled(f"{query!r} {mode} throttled after {MAX_RETRIES} tries")


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
        try:
            payload = get_or_fetch(
                path,
                lambda: _request(query, mode, _stamp(chunk_start), _stamp(chunk_end)),
            )
        except GdeltThrottled as exc:
            print(f"GDELT skip (uncached): {exc}", file=sys.stderr)
            continue
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
