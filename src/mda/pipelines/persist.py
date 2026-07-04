from __future__ import annotations

import hashlib
import json
from datetime import date

import pandas as pd

from mda.paths import config_path
from mda.store import pg

METHOD = "index.v1"


def config_hash() -> str:
    return hashlib.sha1(config_path("index.yaml").read_bytes()).hexdigest()[:16]


def _signal_source(signal_name: str) -> str:
    if signal_name.startswith("gfw"):
        return "gfw"
    if signal_name.startswith("gdelt"):
        return "gdelt"
    return "derived"


def persist_run(signals_df: pd.DataFrame, index_df: pd.DataFrame, contrib_df: pd.DataFrame) -> dict[str, int]:
    chash = config_hash()
    signal_rows = [
        {
            "aoi_id": r["aoi_id"],
            "date": date.fromisoformat(r["date"]),
            "signal_name": r["signal_name"],
            "value": None if pd.isna(r["value"]) else float(r["value"]),
            "method_version": METHOD,
            "source_id": _signal_source(r["signal_name"]),
            "collector": "pipeline:build_signals",
            "raw_ref": "data/processed/signals.parquet",
        }
        for r in signals_df.to_dict("records")
    ]
    index_rows = [
        {
            "aoi_id": r["aoi_id"],
            "date": date.fromisoformat(r["date"]),
            "index_value": float(r["index"]),
            "raw_score": float(r["raw_score"]),
            "level": r["level"],
            "method_version": METHOD,
            "config_hash": chash,
        }
        for r in index_df.to_dict("records")
    ]
    contrib_rows = [
        {
            "aoi_id": r["aoi_id"],
            "date": date.fromisoformat(r["date"]),
            "signal_name": r["signal_name"],
            "z_clip": float(r["z_clip"]),
            "index_points": float(r["index_points"]),
            "method_version": METHOD,
        }
        for r in contrib_df.to_dict("records")
    ]
    with pg.connect() as conn:
        pg.upsert(conn, "method_registry", [{"method_version": METHOD, "config_snapshot": json.dumps({"config_hash": chash})}], conflict=["method_version"], update=["config_snapshot"])
        pg.upsert(conn, "signal_daily", signal_rows, conflict=["aoi_id", "date", "signal_name", "method_version"], update=["value"])
        pg.upsert(conn, "index_daily", index_rows, conflict=["aoi_id", "date", "method_version"], update=["index_value", "raw_score", "level", "config_hash"])
        pg.upsert(conn, "index_contribution", contrib_rows, conflict=["aoi_id", "date", "signal_name", "method_version"], update=["z_clip", "index_points"])
    return {"signal_daily": len(signal_rows), "index_daily": len(index_rows), "index_contribution": len(contrib_rows)}
