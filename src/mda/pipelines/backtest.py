from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from mda.config import Event, IndexConfig

EVENT_GUARD_DAYS = 21
PEAK_WINDOW_BEFORE = 14


def _aoi_series(index_df: pd.DataFrame, aoi_id: str) -> pd.Series:
    rows = index_df[index_df["aoi_id"] == aoi_id].copy()
    rows["date"] = pd.to_datetime(rows["date"])
    return rows.set_index("date")["index"].sort_index()


def _lead_time_days(series: pd.Series, event: Event, watch: float) -> int | None:
    event_ts = pd.Timestamp(event.event_date)
    window = series[
        (series.index >= event_ts - timedelta(days=event.search_days_before))
        & (series.index <= event_ts + timedelta(days=event.search_days_after))
    ]
    crossings = window[window >= watch]
    if crossings.empty:
        return None
    return (event_ts - crossings.index[0]).days


def _peak(series: pd.Series, event: Event) -> tuple[float, pd.Timestamp | None]:
    event_ts = pd.Timestamp(event.event_date)
    window = series[
        (series.index >= event_ts - timedelta(days=PEAK_WINDOW_BEFORE))
        & (series.index <= event_ts + timedelta(days=event.search_days_after))
    ]
    if window.empty:
        return 0.0, None
    return float(window.max()), window.idxmax()


def _control_mask(series: pd.Series, events: list[Event], aoi_id: str) -> pd.Series:
    mask = pd.Series(True, index=series.index)
    for event in events:
        if event.aoi_id != aoi_id:
            continue
        event_ts = pd.Timestamp(event.event_date)
        mask &= ~(
            (series.index >= event_ts - timedelta(days=EVENT_GUARD_DAYS))
            & (series.index <= event_ts + timedelta(days=EVENT_GUARD_DAYS))
        )
    return mask


def _peak_percentile(series: pd.Series, control: pd.Series, peak_value: float) -> float:
    if control.empty:
        return float("nan")
    return round(float((control <= peak_value).mean() * 100.0), 1)


def _false_positive_episodes(series: pd.Series, control_mask: pd.Series, watch: float) -> int:
    outside = series[control_mask]
    crossing = outside >= watch
    episodes = 0
    prev = False
    for value in crossing:
        if value and not prev:
            episodes += 1
        prev = value
    return episodes


def run_backtest(index_df: pd.DataFrame, events: list[Event], cfg: IndexConfig) -> list[dict]:
    results = []
    for event in events:
        series = _aoi_series(index_df, event.aoi_id)
        if series.empty:
            results.append({"event_id": event.event_id, "aoi_id": event.aoi_id, "status": "no_data"})
            continue
        watch = cfg.thresholds.watch
        lead = _lead_time_days(series, event, watch)
        peak_value, peak_date = _peak(series, event)
        mask = _control_mask(series, events, event.aoi_id)
        control = series[mask]
        results.append(
            {
                "event_id": event.event_id,
                "aoi_id": event.aoi_id,
                "event_date": event.event_date.isoformat(),
                "lead_time_days": lead,
                "peak_index": round(peak_value, 1),
                "peak_date": peak_date.date().isoformat() if peak_date is not None else None,
                "peak_percentile": _peak_percentile(series, control, peak_value),
                "false_positive_episodes": _false_positive_episodes(series, mask, watch),
            }
        )
    return results
