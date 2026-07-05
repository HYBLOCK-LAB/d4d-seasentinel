from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from mda.collectors.gfw import _polygon, token
from mda.config import Aoi, Region, load_aois, load_regions
from mda.paths import data_dir
from mda.pipelines.persist import METHOD
from mda.store import pg
from mda.store.cache import cache_key, get_or_fetch

BASE = "https://gateway.api.globalfishingwatch.org/v3/events"
LIMIT = 100_000
LOG = logging.getLogger(__name__)

DATASETS = {
    "port": ("public-global-port-visits-events:latest", "gfw_port_visit"),
    "encounter": ("public-global-encounters-events:latest", "gfw_encounter"),
    "loitering": ("public-global-loitering-events:latest", "gfw_loitering"),
    "gap": ("public-global-gaps-events:latest", "gfw_gap"),
    "fishing": ("public-global-fishing-events:latest", "gfw_fishing"),
}


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _bbox_contains(bbox: list[float], lon: float, lat: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def _region_id(lon: float, lat: float, regions: list[Region]) -> str | None:
    for region in regions:
        if _bbox_contains(region.bbox, lon, lat):
            return region.region_id
    return None


def _requested_regions(region_ids: list[str]) -> list[Region]:
    by_id = {r.region_id: r for r in load_regions()}
    missing = [rid for rid in region_ids if rid not in by_id]
    if missing:
        raise ValueError(f"unknown regions: {', '.join(missing)}")
    return [by_id[rid] for rid in region_ids]


def _staging_aois() -> list[Aoi]:
    return [a for a in load_aois() if a.region_id == "south_china_sea" and a.role == "staging"]


def _event_position(entry: dict) -> tuple[float, float] | None:
    pos = entry.get("position") or {}
    lon, lat = pos.get("lon"), pos.get("lat")
    if lon is None or lat is None:
        return None
    return float(lon), float(lat)


def _event_row(entry: dict, short: str, regions: list[Region]) -> tuple[dict, int | None] | None:
    pos = _event_position(entry)
    if pos is None or not entry.get("id") or not entry.get("start"):
        return None
    lon, lat = pos
    ts = _parse_ts(entry["start"])
    event_type = DATASETS[short][1]
    event_id = f"gfw:{short}:{entry['id']}"
    vessel = entry.get("vessel") or {}
    ssvid = vessel.get("ssvid")
    row = {
        "event_id": event_id,
        "name": f"GFW {entry.get('type') or short} {entry['id']}",
        "event_type": event_type,
        "event_date": ts.date(),
        "zone_id": None,
        "aoi_id": None,
        "region_id": _region_id(lon, lat, regions),
        "geom": f"SRID=4326;POINT({lon} {lat})",
        "description": json.dumps(
            {
                "start": entry.get("start"),
                "end": entry.get("end"),
                "type": entry.get("type"),
                "vessel": vessel,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        "citations": [DATASETS[short][0]],
        "source_id": "gfw_events",
        "collector": "gfw_events",
        "raw_ref": entry["id"],
    }
    return row, int(ssvid) if ssvid and str(ssvid).isdigit() else None


def _signal_rows(port_entries: list[dict], aois: list[Aoi], start: date, end: date) -> list[dict]:
    counts: Counter[tuple[str, date]] = Counter()
    for entry in port_entries:
        pos = _event_position(entry)
        if pos is None or not entry.get("start"):
            continue
        lon, lat = pos
        day = _parse_ts(entry["start"]).date()
        if day < start or day > end:
            continue
        for aoi in aois:
            if _bbox_contains(aoi.bbox, lon, lat):
                counts[(aoi.aoi_id, day)] += 1
    rows = []
    cursor = start
    while cursor <= end:
        for aoi in aois:
            rows.append(
                {
                    "aoi_id": aoi.aoi_id,
                    "date": cursor,
                    "signal_name": "gfw_port_visit_count",
                    "value": float(counts[(aoi.aoi_id, cursor)]),
                    "method_version": METHOD,
                    "source_id": "gfw_events",
                    "collector": "gfw_events",
                    "raw_ref": "data/raw/gfw_events",
                }
            )
        cursor += timedelta(days=1)
    return rows


def _headers() -> dict[str, str]:
    auth = token()
    if not auth:
        raise RuntimeError("GFW_TOKEN not set")
    return {"Authorization": f"Bearer {auth}"}


def _get_page(client: httpx.Client, dataset: str, start: date, end: date, limit: int, offset: int, bbox: list[float] | None = None) -> dict:
    params: dict[str, Any] = {
        "datasets[0]": dataset,
        "start-date": start.isoformat(),
        "end-date": end.isoformat(),
        "limit": limit,
        "offset": offset,
    }
    if bbox is not None:
        params["bbox"] = ",".join(str(x) for x in bbox)
    resp = client.get(BASE, params=params)
    resp.raise_for_status()
    return resp.json()


def _post_page(client: httpx.Client, dataset: str, start: date, end: date, limit: int, offset: int, bbox: list[float]) -> dict:
    params = {
        "datasets[0]": dataset,
        "start-date": start.isoformat(),
        "end-date": end.isoformat(),
        "limit": limit,
        "offset": offset,
    }
    resp = client.post(BASE, params=params, json={"region": {"geojson": _polygon(bbox)}})
    resp.raise_for_status()
    return resp.json()


def _probe_mode(client: httpx.Client, dataset: str, start: date, end: date, bbox: list[float]) -> str:
    try:
        _get_page(client, dataset, start, end, 1, 0, bbox=bbox)
        return "get_bbox"
    except httpx.HTTPStatusError as exc:
        LOG.info("GFW GET bbox unsupported status=%s", exc.response.status_code)
    try:
        _post_page(client, dataset, start, end, 1, 0, bbox)
        return "post_region"
    except httpx.HTTPStatusError as exc:
        LOG.info("GFW POST region unavailable status=%s; falling back to GET+local bbox filter", exc.response.status_code)
    return "get_local"


def _cached_page(
    client: httpx.Client,
    mode: str,
    short: str,
    dataset: str,
    start: date,
    end: date,
    limit: int,
    offset: int,
    bbox: list[float],
) -> dict:
    key = cache_key("events", mode, short, start.isoformat(), end.isoformat(), str(limit), str(offset), ",".join(str(x) for x in bbox))
    path = data_dir("raw", "gfw_events", f"{key}.json")

    def fetch() -> dict:
        if mode == "get_bbox":
            return _get_page(client, dataset, start, end, limit, offset, bbox=bbox)
        if mode == "post_region":
            return _post_page(client, dataset, start, end, limit, offset, bbox)
        return _get_page(client, dataset, start, end, limit, offset)

    return get_or_fetch(path, fetch)


def _iter_pages(
    client: httpx.Client,
    mode: str,
    short: str,
    dataset: str,
    start: date,
    end: date,
    bbox: list[float],
    limit: int,
):
    offset = 0
    total = None
    while total is None or offset < total:
        page = _cached_page(client, mode, short, dataset, start, end, limit, offset, bbox)
        yield page
        total = int(page.get("total") or 0)
        next_offset = page.get("nextOffset")
        entries = page.get("entries") or []
        if next_offset is None:
            offset += len(entries)
        else:
            offset = int(next_offset)
        if not entries or offset == 0:
            break


def _existing_vessel_links(conn, event_mmsi: dict[str, int]) -> list[dict]:
    if not event_mmsi:
        return []
    mmsis = sorted(set(event_mmsi.values()))
    with conn.cursor() as cur:
        cur.execute("select mmsi, vessel_id from vessel where mmsi = any(%s)", (mmsis,))
        vessel_by_mmsi = {int(mmsi): vessel_id for mmsi, vessel_id in cur.fetchall()}
    rows = []
    for event_id, mmsi in event_mmsi.items():
        vessel_id = vessel_by_mmsi.get(mmsi)
        if not vessel_id:
            continue
        rows.append(
            {
                "link_id": f"gfw_event_vessel:{event_id}:{vessel_id}",
                "src_type": "event",
                "src_id": event_id,
                "dst_type": "vessel",
                "dst_id": vessel_id,
                "rel_type": "observed_vessel",
                "confidence": 0.95,
                "hypothesis": False,
                "method_version": None,
                "source_id": "gfw_events",
                "collector": "gfw_events",
                "raw_ref": event_id,
            }
        )
    return rows


def collect(start: date, end: date, region_ids: list[str], limit: int = LIMIT) -> dict[str, int]:
    requested_regions = _requested_regions(region_ids)
    all_regions = load_regions()
    staging_aois = _staging_aois()
    probe_bbox = requested_regions[0].bbox
    rows_by_id: dict[str, dict] = {}
    event_mmsi: dict[str, int] = {}
    port_entries: list[dict] = []
    port_entry_ids: set[str] = set()
    seen_by_type: Counter[str] = Counter()

    with httpx.Client(headers=_headers(), timeout=120.0, follow_redirects=True) as client:
        first_dataset = next(iter(DATASETS.values()))[0]
        mode = _probe_mode(client, first_dataset, start, end, probe_bbox)
        for short, (dataset, event_type) in DATASETS.items():
            page_bboxes = [probe_bbox]
            if mode != "get_local":
                page_bboxes = [region.bbox for region in requested_regions]
                if event_type == "gfw_port_visit":
                    page_bboxes.extend(aoi.bbox for aoi in staging_aois)
            for bbox in page_bboxes:
                for page in _iter_pages(client, mode, short, dataset, start, end, bbox, limit):
                    for entry in page.get("entries") or []:
                        pos = _event_position(entry)
                        if pos is None:
                            continue
                        lon, lat = pos
                        in_requested_region = any(_bbox_contains(region.bbox, lon, lat) for region in requested_regions)
                        in_staging_aoi = event_type == "gfw_port_visit" and any(_bbox_contains(aoi.bbox, lon, lat) for aoi in staging_aois)
                        if not in_requested_region and not in_staging_aoi:
                            continue
                        if in_staging_aoi and entry.get("id") not in port_entry_ids:
                            port_entries.append(entry)
                            port_entry_ids.add(entry.get("id"))
                        if not in_requested_region:
                            continue
                        parsed = _event_row(entry, short, all_regions)
                        if parsed is None:
                            continue
                        row, mmsi = parsed
                        rows_by_id[row["event_id"]] = row
                        if mmsi is not None:
                            event_mmsi[row["event_id"]] = mmsi
                        seen_by_type[event_type] += 1

    signal_rows = _signal_rows(port_entries, staging_aois, start, end)
    links: list[dict] = []
    with pg.connect() as conn:
        pg.upsert(
            conn,
            "event",
            list(rows_by_id.values()),
            conflict=["event_id"],
            update=["name", "event_type", "event_date", "region_id", "geom", "description", "citations", "raw_ref"],
        )
        links = _existing_vessel_links(conn, event_mmsi)
        pg.upsert(conn, "entity_link", links, conflict=["link_id"], update=["confidence", "raw_ref"])
        pg.upsert(
            conn,
            "signal_daily",
            signal_rows,
            conflict=["aoi_id", "date", "signal_name", "method_version"],
            update=["value", "raw_ref"],
        )
    result = {f"event_{k}": v for k, v in sorted(seen_by_type.items())}
    result["events"] = len(rows_by_id)
    result["entity_links"] = len(links)
    result["signal_daily"] = len(signal_rows)
    return result
