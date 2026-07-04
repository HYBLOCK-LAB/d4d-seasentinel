from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv

from presail.cache import cache_key, get_or_fetch
from presail.paths import data_dir, repo_root

BASE = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
CHUNK_DAYS = 180
VALUE_FIELD = {
    "public-global-presence:latest": "hours",
    "public-global-sar-presence:latest": "detections",
}

_token_loaded = False


def token() -> str | None:
    global _token_loaded
    if not _token_loaded:
        load_dotenv(repo_root() / ".env")
        _token_loaded = True
    return os.environ.get("GFW_TOKEN") or None


def _polygon(bbox: list[float]) -> dict:
    min_lon, min_lat, max_lon, max_lat = bbox
    ring = [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _request(dataset: str, bbox: list[float], start: date, end: date) -> list[dict]:
    auth = token()
    if not auth:
        raise RuntimeError("GFW_TOKEN not set")
    params = {
        "spatial-resolution": "LOW",
        "temporal-resolution": "DAILY",
        "datasets[0]": dataset,
        "date-range": f"{start.isoformat()},{end.isoformat()}",
        "format": "JSON",
    }
    resp = httpx.post(
        BASE,
        params=params,
        headers={"Authorization": f"Bearer {auth}"},
        json={"geojson": _polygon(bbox)},
        timeout=120.0,
    )
    resp.raise_for_status()
    field = VALUE_FIELD[dataset]
    totals: dict[str, float] = defaultdict(float)
    for entry in resp.json().get("entries", []):
        for rows in entry.values():
            for row in rows or []:
                totals[row["date"]] += row.get(field, 0) or 0
    return [{"date": day, "value": totals[day]} for day in sorted(totals)]


def _chunks(start: date, end: date):
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=CHUNK_DAYS), end)
        yield cursor, stop
        cursor = stop


def fetch_4wings_daily(dataset: str, aoi_id: str, bbox: list[float], start: date, end: date) -> list[dict]:
    merged: dict[str, float] = {}
    for chunk_start, chunk_end in _chunks(start, end):
        key = cache_key(dataset, aoi_id, chunk_start.isoformat(), chunk_end.isoformat())
        path = data_dir("raw", "gfw", f"{key}.json")
        rows = get_or_fetch(path, lambda: _request(dataset, bbox, chunk_start, chunk_end))
        for row in rows:
            merged[row["date"]] = row["value"]
    return [{"date": day, "value": merged[day]} for day in sorted(merged)]
