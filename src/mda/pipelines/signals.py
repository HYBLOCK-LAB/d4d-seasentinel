from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from mda.collectors.gdelt import fetch_volraw_and_tone
from mda.collectors.gfw import fetch_4wings_daily, token
from mda.config import Aoi, Event, IndexConfig, load_aois, load_events, load_index_config
from mda.paths import data_dir

WINDOW_PAD_DAYS = 20

GFW_DATASETS = {
    "gfw_presence_hours": "public-global-presence:latest",
    "gfw_sar_presence": "public-global-sar-presence:latest",
}
STAGING_SIGNAL = "gfw_staging_presence_hours"


def _gdelt_rows(aoi: Aoi, start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    for signal_name, query in aoi.queries.items():
        with_tone = signal_name == "gdelt_place_en"
        points = fetch_volraw_and_tone(query, start, end, include_tone=with_tone)
        for point in points:
            share = point["article_count"] / max(point["monitored_volume"], 1.0) * 10000.0
            rows.append({"date": point["date"], "aoi_id": aoi.aoi_id, "signal_name": signal_name, "value": share})
            if with_tone and point["tone"] is not None:
                rows.append(
                    {
                        "date": point["date"],
                        "aoi_id": aoi.aoi_id,
                        "signal_name": "gdelt_tone",
                        "value": -point["tone"],
                    }
                )
    return rows


def _gfw_rows(aoi: Aoi, start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    for signal_name, dataset in GFW_DATASETS.items():
        daily = fetch_4wings_daily(dataset, aoi.aoi_id, aoi.bbox, start, end)
        for point in daily:
            rows.append(
                {"date": point["date"], "aoi_id": aoi.aoi_id, "signal_name": signal_name, "value": point["value"]}
            )
    return rows


def _event_window(event: Event, cfg: IndexConfig, start: date, end: date) -> tuple[date, date] | None:
    lead = cfg.baseline_days + cfg.embargo_days + event.search_days_before + WINDOW_PAD_DAYS
    window_start = max(start, event.event_date - timedelta(days=lead))
    window_end = min(end, event.event_date + timedelta(days=event.search_days_after + WINDOW_PAD_DAYS))
    if window_start >= window_end:
        return None
    return window_start, window_end


def _collection_tasks(
    aois: list[Aoi],
    events: dict[str, Event],
    cfg: IndexConfig,
    start: date,
    end: date,
    event_windows: bool,
) -> list[tuple[Aoi, date, date, str | None]]:
    tasks: list[tuple[Aoi, date, date, str | None]] = []
    for aoi in aois:
        if not event_windows:
            tasks.append((aoi, start, end, None))
            continue
        if aoi.aoi_id in events:
            window = _event_window(events[aoi.aoi_id], cfg, start, end)
            if window:
                tasks.append((aoi, window[0], window[1], None))
        for target in aoi.staging_for:
            if target in events:
                window = _event_window(events[target], cfg, start, end)
                if window:
                    tasks.append((aoi, window[0], window[1], target))
    return tasks


def build_signals(start: date, end: date, gdelt_only: bool = False, event_windows: bool = True) -> pd.DataFrame:
    use_gfw = not gdelt_only and token() is not None
    cfg = load_index_config()
    aois = load_aois()
    events = {e.aoi_id: e for e in load_events()}

    rows: list[dict] = []
    for aoi, win_start, win_end, target in _collection_tasks(aois, events, cfg, start, end, event_windows):
        rows.extend(_gdelt_rows(aoi, win_start, win_end))
        if use_gfw:
            gfw_rows = _gfw_rows(aoi, win_start, win_end)
            rows.extend(gfw_rows)
            if target is not None:
                rows.extend(
                    {"date": r["date"], "aoi_id": target, "signal_name": STAGING_SIGNAL, "value": r["value"]}
                    for r in gfw_rows
                    if r["signal_name"] == "gfw_presence_hours"
                )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["date", "aoi_id", "signal_name"], keep="first").reset_index(drop=True)
    path = data_dir("processed", "signals.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame
