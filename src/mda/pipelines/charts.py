from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from mda.config import Event, IndexConfig
from mda.paths import repo_root

WINDOW_PAD_DAYS = 20


def _window(event: Event):
    event_ts = pd.Timestamp(event.event_date)
    start = event_ts - timedelta(days=event.search_days_before + WINDOW_PAD_DAYS)
    end = event_ts + timedelta(days=event.search_days_after + WINDOW_PAD_DAYS)
    return event_ts, start, end


def _slice(df: pd.DataFrame, aoi_id: str, start, end) -> pd.DataFrame:
    rows = df[df["aoi_id"] == aoi_id].copy()
    rows["date"] = pd.to_datetime(rows["date"])
    return rows[(rows["date"] >= start) & (rows["date"] <= end)].sort_values("date")


def plot_timeline(index_df: pd.DataFrame, event: Event, cfg: IndexConfig, out_path: Path) -> None:
    event_ts, start, end = _window(event)
    rows = _slice(index_df, event.aoi_id, start, end)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(rows["date"], rows["index"], color="#1f4e79", linewidth=1.8, label="Pre-Sail Index")
    ax.axhline(cfg.thresholds.watch, color="#e08e0b", linestyle="--", linewidth=1, label="WATCH")
    ax.axhline(cfg.thresholds.alert, color="#c0392b", linestyle="--", linewidth=1, label="ALERT")
    ax.axvline(event_ts, color="#333333", linestyle=":", linewidth=1.5, label="Event")
    ax.set_ylim(0, 100)
    ax.set_title(f"{event.name}", fontsize=11)
    ax.set_ylabel("Index (0-100)")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_contributions(contrib_df: pd.DataFrame, event: Event, out_path: Path) -> None:
    event_ts, start, end = _window(event)
    rows = _slice(contrib_df, event.aoi_id, start, end)
    if rows.empty:
        return
    wide = rows.pivot_table(index="date", columns="signal_name", values="index_points", aggfunc="sum").fillna(0.0)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.stackplot(wide.index, wide.T.values, labels=list(wide.columns))
    ax.axvline(event_ts, color="#333333", linestyle=":", linewidth=1.5)
    ax.set_title(f"{event.name} — signal contributions", fontsize=11)
    ax.set_ylabel("Index points")
    ax.legend(fontsize=7, loc="upper left", ncol=2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def render_event_charts(index_df: pd.DataFrame, contrib_df: pd.DataFrame, event: Event, cfg: IndexConfig) -> dict:
    charts_dir = repo_root() / "charts"
    charts_dir.mkdir(exist_ok=True)
    timeline = charts_dir / f"{event.aoi_id}_{event.event_id}_timeline.png"
    contributions = charts_dir / f"{event.aoi_id}_{event.event_id}_contributions.png"
    plot_timeline(index_df, event, cfg, timeline)
    plot_contributions(contrib_df, event, contributions)
    return {
        "chart_timeline": str(timeline.relative_to(repo_root())),
        "chart_contributions": str(contributions.relative_to(repo_root())),
    }
