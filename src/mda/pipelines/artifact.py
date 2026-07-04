from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from mda.config import Aoi, Event, IndexConfig

TOP_EVIDENCE = 5


def _aoi_series(index_df: pd.DataFrame, contrib_df: pd.DataFrame, aoi: Aoi) -> dict:
    rows = index_df[index_df["aoi_id"] == aoi.aoi_id].sort_values("date")
    contrib = contrib_df[contrib_df["aoi_id"] == aoi.aoi_id]
    series = []
    for _, row in rows.iterrows():
        day_contrib = contrib[contrib["date"] == row["date"]]
        contributions = {
            r["signal_name"]: round(float(r["index_points"]), 2) for _, r in day_contrib.iterrows()
        }
        series.append(
            {
                "date": row["date"],
                "index": float(row["index"]),
                "level": row["level"],
                "raw_score": float(row["raw_score"]),
                "contributions": contributions,
            }
        )
    return {
        "aoi_id": aoi.aoi_id,
        "name": aoi.name,
        "bbox": aoi.bbox,
        "series": series,
    }


def _composite(index_df: pd.DataFrame) -> list[dict]:
    if index_df.empty:
        return []
    idx = index_df.loc[index_df.groupby("date")["index"].idxmax()]
    return [
        {"date": row["date"], "index": float(row["index"]), "driving_aoi": row["aoi_id"]}
        for _, row in idx.sort_values("date").iterrows()
    ]


def build_artifact(
    index_df: pd.DataFrame,
    contrib_df: pd.DataFrame,
    aois: list[Aoi],
    events: list[Event],
    backtests: list[dict],
    cfg: IndexConfig,
) -> dict:
    indexed_ids = set(index_df["aoi_id"].unique())
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "thresholds": {"watch": cfg.thresholds.watch, "alert": cfg.thresholds.alert},
        "aois": [_aoi_series(index_df, contrib_df, a) for a in aois if a.aoi_id in indexed_ids],
        "composite": {"series": _composite(index_df)},
        "backtests": backtests,
    }
