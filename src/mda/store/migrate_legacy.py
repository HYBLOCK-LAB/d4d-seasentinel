from __future__ import annotations

import json
import math
from datetime import date

import pandas as pd

from mda.config import load_aois, load_events, load_regions, load_sources
from mda.paths import data_dir
from mda.store import pg

LEGACY_METHOD = "legacy.v0"


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _signal_source(signal_name: str) -> str:
    if signal_name.startswith("gfw"):
        return "gfw"
    if signal_name.startswith("gdelt"):
        return "gdelt"
    return "unknown"


def _bbox_ewkt(bbox: list[float]) -> str:
    min_lon, min_lat, max_lon, max_lat = bbox
    ring = (
        f"{min_lon} {min_lat}, {max_lon} {min_lat}, {max_lon} {max_lat}, "
        f"{min_lon} {max_lat}, {min_lon} {min_lat}"
    )
    return f"SRID=4326;POLYGON(({ring}))"


def _migrate_sources(conn) -> int:
    rows = [
        {
            "source_id": s.source_id,
            "kind": s.kind,
            "base_url": s.base_url,
            "license": s.license,
            "description": None,
        }
        for s in load_sources()
    ]
    return pg.upsert(conn, "source", rows, conflict=["source_id"], update=["kind", "base_url", "license"])


def _migrate_method(conn) -> int:
    row = [{"method_version": LEGACY_METHOD, "description": "presail batch pipeline pre-integration"}]
    return pg.upsert(conn, "method_registry", row, conflict=["method_version"])


def _migrate_zones(conn) -> int:
    rows = []
    for region in load_regions():
        rows.append(
            {
                "zone_id": f"region:{region.region_id}",
                "name": region.name,
                "kind": "region",
                "role": region.priority,
                "region_id": region.region_id,
                "geom": _bbox_ewkt(region.bbox),
                "source_id": "config",
                "collector": "migration:regions_yaml",
                "raw_ref": "config/regions.yaml",
            }
        )
    for aoi in load_aois():
        rows.append(
            {
                "zone_id": f"aoi:{aoi.aoi_id}",
                "name": aoi.name,
                "kind": "aoi",
                "role": aoi.role,
                "region_id": aoi.region_id,
                "geom": _bbox_ewkt(aoi.bbox),
                "source_id": "config",
                "collector": "migration:aois_yaml",
                "raw_ref": "config/aois.yaml",
            }
        )
    return pg.upsert(
        conn, "zone", rows, conflict=["zone_id"], update=["name", "kind", "role", "region_id", "geom"]
    )


def _migrate_events(conn) -> int:
    events = load_events()
    event_rows = [
        {
            "event_id": e.event_id,
            "name": e.name,
            "event_type": e.event_type,
            "event_date": e.event_date,
            "zone_id": f"aoi:{e.aoi_id}",
            "aoi_id": e.aoi_id,
            "description": e.description,
            "citations": e.citations or None,
            "source_id": "config",
            "collector": "migration:events_yaml",
            "raw_ref": "config/events.yaml",
        }
        for e in events
    ]
    pg.upsert(
        conn,
        "event",
        event_rows,
        conflict=["event_id"],
        update=["name", "event_date", "zone_id", "aoi_id"],
    )
    cfg_rows = [
        {
            "event_id": e.event_id,
            "search_days_before": e.search_days_before,
            "search_days_after": e.search_days_after,
        }
        for e in events
    ]
    pg.upsert(
        conn,
        "backtest_config",
        cfg_rows,
        conflict=["event_id"],
        update=["search_days_before", "search_days_after"],
    )
    return len(event_rows)


def _migrate_signals(conn) -> int:
    path = data_dir("processed", "signals.parquet")
    df = pd.read_parquet(path)
    rows = [
        {
            "aoi_id": r["aoi_id"],
            "date": date.fromisoformat(r["date"]),
            "signal_name": r["signal_name"],
            "value": _clean(r["value"]),
            "method_version": LEGACY_METHOD,
            "source_id": _signal_source(r["signal_name"]),
            "collector": "migration:signals_parquet",
            "raw_ref": "data/processed/signals.parquet",
        }
        for r in df.to_dict("records")
    ]
    return pg.upsert(
        conn,
        "signal_daily",
        rows,
        conflict=["aoi_id", "date", "signal_name", "method_version"],
        update=["value"],
    )


def _migrate_index(conn) -> int:
    path = data_dir("processed", "index.parquet")
    df = pd.read_parquet(path)
    rows = [
        {
            "aoi_id": r["aoi_id"],
            "date": date.fromisoformat(r["date"]),
            "index_value": _clean(r["index"]),
            "raw_score": _clean(r["raw_score"]),
            "level": r["level"],
            "method_version": LEGACY_METHOD,
            "config_hash": None,
        }
        for r in df.to_dict("records")
    ]
    return pg.upsert(
        conn,
        "index_daily",
        rows,
        conflict=["aoi_id", "date", "method_version"],
        update=["index_value", "raw_score", "level"],
    )


def _migrate_contributions(conn) -> int:
    path = data_dir("processed", "contributions.parquet")
    df = pd.read_parquet(path)
    rows = [
        {
            "aoi_id": r["aoi_id"],
            "date": date.fromisoformat(r["date"]),
            "signal_name": r["signal_name"],
            "z_clip": _clean(r["z_clip"]),
            "index_points": _clean(r["index_points"]),
            "method_version": LEGACY_METHOD,
        }
        for r in df.to_dict("records")
    ]
    return pg.upsert(
        conn,
        "index_contribution",
        rows,
        conflict=["aoi_id", "date", "signal_name", "method_version"],
        update=["z_clip", "index_points"],
    )


def _migrate_artifact(conn) -> int:
    path = data_dir("artifacts", "latest.json")
    if not path.exists():
        return 0
    payload = json.loads(path.read_text())
    row = [
        {
            "snapshot_id": "legacy:latest",
            "schema_version": payload.get("schema_version"),
            "generated_at": payload.get("generated_at"),
            "payload": json.dumps(payload),
            "source_id": "presail",
            "collector": "migration:artifact_json",
            "raw_ref": "data/artifacts/latest.json",
        }
    ]
    return pg.upsert(
        conn,
        "artifact_snapshot",
        row,
        conflict=["snapshot_id"],
        update=["schema_version", "generated_at", "payload"],
    )


def migrate() -> dict[str, int]:
    counts: dict[str, int] = {}
    with pg.connect() as conn:
        pg.ensure_schema(conn)
        counts["source"] = _migrate_sources(conn)
        counts["method_registry"] = _migrate_method(conn)
        counts["zone"] = _migrate_zones(conn)
        counts["event"] = _migrate_events(conn)
        counts["signal_daily"] = _migrate_signals(conn)
        counts["index_daily"] = _migrate_index(conn)
        counts["index_contribution"] = _migrate_contributions(conn)
        counts["artifact_snapshot"] = _migrate_artifact(conn)
    return counts


def verify() -> dict[str, dict]:
    signals = len(pd.read_parquet(data_dir("processed", "signals.parquet")))
    index = len(pd.read_parquet(data_dir("processed", "index.parquet")))
    contrib = len(pd.read_parquet(data_dir("processed", "contributions.parquet")))
    aois = load_aois()
    regions = load_regions()
    events = load_events()
    with pg.connect(readonly=True) as conn:
        db = {
            "signal_daily": pg.count(conn, "signal_daily"),
            "index_daily": pg.count(conn, "index_daily"),
            "index_contribution": pg.count(conn, "index_contribution"),
            "zone": pg.count(conn, "zone"),
            "event": pg.count(conn, "event"),
        }
    expected = {
        "signal_daily": signals,
        "index_daily": index,
        "index_contribution": contrib,
        "zone": len(aois) + len(regions),
        "event": len(events),
    }
    return {k: {"expected": expected[k], "db": db[k], "ok": expected[k] == db[k]} for k in expected}
