from __future__ import annotations

from datetime import date

import httpx

from mda.config import load_regions
from mda.paths import data_dir
from mda.store import pg
from mda.store.cache import cache_key, get_or_fetch

MARINE = "https://marine-api.open-meteo.com/v1/marine"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def _center(bbox: list[float]) -> tuple[float, float]:
    min_lon, min_lat, max_lon, max_lat = bbox
    return round((min_lat + max_lat) / 2, 3), round((min_lon + max_lon) / 2, 3)


def _fetch(url: str, params: dict) -> dict:
    resp = httpx.get(url, params=params, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def _daily(url: str, lat: float, lon: float, variable: str, start: date, end: date) -> dict[str, float]:
    key = cache_key(url, f"{lat},{lon}", variable, start.isoformat(), end.isoformat())
    path = data_dir("raw", "openmeteo", f"{key}.json")
    payload = get_or_fetch(
        path,
        lambda: _fetch(
            url,
            {
                "latitude": lat,
                "longitude": lon,
                "daily": variable,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "UTC",
            },
        ),
    )
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    values = daily.get(variable) or []
    return {t: v for t, v in zip(times, values)}


def collect(start: date, end: date) -> dict:
    rows = []
    for region in load_regions():
        lat, lon = _center(region.bbox)
        waves = _daily(MARINE, lat, lon, "wave_height_max", start, end)
        winds = _daily(ARCHIVE, lat, lon, "wind_speed_10m_max", start, end)
        for day in sorted(set(waves) | set(winds)):
            rows.append(
                {
                    "region_id": region.region_id,
                    "date": date.fromisoformat(day),
                    "wind_speed": winds.get(day),
                    "wave_height": waves.get(day),
                    "visibility": None,
                    "source_id": "open_meteo",
                    "collector": "weather_openmeteo",
                    "raw_ref": None,
                }
            )
    with pg.connect() as conn:
        pg.upsert(
            conn,
            "weather_daily",
            rows,
            conflict=["region_id", "date"],
            update=["wind_speed", "wave_height", "visibility"],
        )
    return {"weather_rows": len(rows), "regions": len({r["region_id"] for r in rows})}
