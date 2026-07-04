from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone

import websockets
from dotenv import load_dotenv

from mda.config import load_regions
from mda.paths import repo_root
from mda.store import lake, pg

URL = "wss://stream.aisstream.io/v0/stream"
POSITION_TYPES = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}
STATIC_TYPES = {"ShipStaticData", "StaticDataReport"}
DEFAULT_TYPES = ["PositionReport", "ShipStaticData", "StandardClassBPositionReport", "StaticDataReport"]
FLUSH_EVERY = 400
FLUSH_INTERVAL = 5.0
BACKOFF_CAP = 30.0

_env_loaded = False


def _api_key() -> str:
    global _env_loaded
    if not _env_loaded:
        load_dotenv(repo_root() / ".env")
        _env_loaded = True
    key = os.environ.get("AISSTREAM_API_KEY")
    if not key:
        raise RuntimeError("AISSTREAM_API_KEY not set")
    return key


def _boxes(region_ids: list[str]) -> tuple[list, dict]:
    regions = {r.region_id: r for r in load_regions()}
    boxes = []
    lookup = {}
    for rid in region_ids:
        r = regions[rid]
        min_lon, min_lat, max_lon, max_lat = r.bbox
        boxes.append([[min_lat, min_lon], [max_lat, max_lon]])
        lookup[rid] = (min_lon, min_lat, max_lon, max_lat)
    return boxes, lookup


def _region_of(lon: float, lat: float, lookup: dict) -> str | None:
    for rid, (min_lon, min_lat, max_lon, max_lat) in lookup.items():
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            return rid
    return None


def _parse_ts(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _meta(msg: dict) -> dict:
    return msg.get("MetaData") or msg.get("Metadata") or {}


def _position_row(msg: dict, msg_type: str, lookup: dict) -> dict | None:
    meta = _meta(msg)
    mmsi = meta.get("MMSI") or meta.get("mmsi")
    lat = meta.get("latitude")
    lon = meta.get("longitude")
    if mmsi is None or lat is None or lon is None:
        return None
    inner = msg.get("Message", {}).get(msg_type, {})
    ts = _parse_ts(meta.get("time_utc"))
    return {
        "mmsi": int(mmsi),
        "ts": ts,
        "vessel_id": f"mmsi:{int(mmsi)}",
        "geom": f"SRID=4326;POINT({lon} {lat})",
        "sog": inner.get("Sog"),
        "cog": inner.get("Cog"),
        "heading": inner.get("TrueHeading"),
        "nav_status": str(inner.get("NavigationalStatus")) if inner.get("NavigationalStatus") is not None else None,
        "msg_type": msg_type,
        "region_id": _region_of(lon, lat, lookup),
        "source_id": "aisstream",
        "collector": "aisstream_realtime",
        "raw_ref": None,
    }


def _vessel_row(msg: dict, msg_type: str) -> dict | None:
    meta = _meta(msg)
    mmsi = meta.get("MMSI") or meta.get("mmsi")
    if mmsi is None:
        return None
    inner = msg.get("Message", {}).get(msg_type, {})
    dim = inner.get("Dimension") or {}
    length = None
    if dim.get("A") is not None and dim.get("B") is not None:
        length = float(dim["A"]) + float(dim["B"])
    imo = inner.get("ImoNumber") or None
    return {
        "vessel_id": f"mmsi:{int(mmsi)}",
        "mmsi": int(mmsi),
        "imo": int(imo) if imo else None,
        "name": (inner.get("Name") or meta.get("ShipName") or "").strip() or None,
        "vessel_type": str(inner.get("Type")) if inner.get("Type") is not None else None,
        "length_m": length,
        "owner": None,
        "source_id": "aisstream",
        "collector": "aisstream_realtime",
        "raw_ref": None,
    }


def _minimal_vessels(positions: list[dict]) -> list[dict]:
    seen = {}
    for p in positions:
        vid = p["vessel_id"]
        if vid not in seen:
            seen[vid] = {
                "vessel_id": vid,
                "mmsi": p["mmsi"],
                "source_id": "aisstream",
                "collector": "aisstream_realtime",
            }
    return list(seen.values())


def _flush(positions: list[dict], vessels: dict[str, dict]) -> None:
    if not positions and not vessels:
        return
    with pg.connect() as conn:
        if positions:
            pg.upsert(conn, "vessel", _minimal_vessels(positions), conflict=["vessel_id"])
        if vessels:
            pg.upsert(
                conn,
                "vessel",
                list(vessels.values()),
                conflict=["vessel_id"],
                update=["mmsi", "imo", "name", "vessel_type", "length_m"],
            )
        if positions:
            pg.upsert(conn, "ais_position", positions, conflict=["mmsi", "ts"])


def _record_gap(started_at: datetime, region_ids: list[str]) -> None:
    with pg.connect() as conn:
        pg.upsert(
            conn,
            "collector_gap",
            [
                {
                    "source_id": "aisstream",
                    "collector": "aisstream_realtime",
                    "region_id": ",".join(region_ids),
                    "started_at": started_at,
                    "ended_at": datetime.now(timezone.utc),
                    "reason": "reconnect",
                }
            ],
            conflict=["gap_id"],
        )


async def run(region_ids: list[str], duration: float | None = None, to_lake: bool = False) -> dict:
    boxes, lookup = _boxes(region_ids)
    subscribe = {
        "APIKey": _api_key(),
        "BoundingBoxes": boxes,
        "FilterMessageTypes": DEFAULT_TYPES,
    }
    deadline = time.monotonic() + duration if duration else None
    stats = {"positions": 0, "vessels": 0, "reconnects": 0}
    backoff = 1.0
    gap_started: datetime | None = None

    while deadline is None or time.monotonic() < deadline:
        try:
            async with websockets.connect(URL, ping_interval=20, max_size=None) as ws:
                await ws.send(json.dumps(subscribe))
                if gap_started is not None:
                    _record_gap(gap_started, region_ids)
                    gap_started = None
                backoff = 1.0
                positions: list[dict] = []
                vessels: dict[str, dict] = {}
                last_flush = time.monotonic()
                seen: set[tuple[int, str]] = set()
                while deadline is None or time.monotonic() < deadline:
                    timeout = None if deadline is None else max(0.1, deadline - time.monotonic())
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    msg = json.loads(raw)
                    msg_type = msg.get("MessageType")
                    if msg_type in POSITION_TYPES:
                        row = _position_row(msg, msg_type, lookup)
                        if row:
                            key = (row["mmsi"], row["ts"].isoformat())
                            if key not in seen:
                                seen.add(key)
                                positions.append(row)
                                stats["positions"] += 1
                    elif msg_type in STATIC_TYPES:
                        row = _vessel_row(msg, msg_type)
                        if row:
                            vessels[row["vessel_id"]] = row
                            stats["vessels"] += 1
                    if len(positions) >= FLUSH_EVERY or (time.monotonic() - last_flush) >= FLUSH_INTERVAL:
                        if to_lake and positions:
                            lake.write_batch("ais_realtime", positions)
                        _flush(positions, vessels)
                        positions, vessels, seen = [], {}, set()
                        last_flush = time.monotonic()
                if to_lake and positions:
                    lake.write_batch("ais_realtime", positions)
                _flush(positions, vessels)
        except asyncio.TimeoutError:
            break
        except (websockets.ConnectionClosed, OSError, json.JSONDecodeError):
            stats["reconnects"] += 1
            if gap_started is None:
                gap_started = datetime.now(timezone.utc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP)
    return stats


def run_sync(region_ids: list[str], duration: float | None = None, to_lake: bool = False) -> dict:
    return asyncio.run(run(region_ids, duration=duration, to_lake=to_lake))
