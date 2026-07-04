from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from presail.config import Aoi, Event, load_aois, load_events, load_index_config
from presail.gdelt import fetch_volraw_and_tone
from presail.gfw import fetch_4wings_daily, token
from presail.paths import data_dir

WINDOW_PAD_DAYS = 20

GDELT_QUERIES = {
    "whitsun_reef": {
        "gdelt_place_en": '("Whitsun Reef" OR "Julian Felipe Reef")',
        "gdelt_place_zh": '"牛轭礁"',
        "gdelt_militia_en": '"maritime militia" ("Whitsun Reef" OR "Julian Felipe Reef" OR "South China Sea")',
        "gdelt_militia_zh": '"海上民兵" ("南沙" OR "南海")',
    },
    "scarborough_shoal": {
        "gdelt_place_en": '("Scarborough Shoal" OR "Bajo de Masinloc")',
        "gdelt_place_zh": '"黄岩岛"',
        "gdelt_militia_en": '"China Coast Guard" ("Scarborough Shoal" OR "Bajo de Masinloc")',
        "gdelt_militia_zh": '"海上民兵" ("南海")',
    },
    "sabina_shoal": {
        "gdelt_place_en": '("Sabina Shoal" OR "Escoda Shoal")',
        "gdelt_place_zh": '"仙宾礁"',
        "gdelt_militia_en": '"China Coast Guard" ("Sabina Shoal" OR "Escoda Shoal")',
        "gdelt_militia_zh": '"海上民兵" ("南沙" OR "南海")',
    },
}

GFW_DATASETS = {
    "gfw_presence_hours": "public-global-presence:latest",
    "gfw_sar_presence": "public-global-sar-presence:latest",
}


def _gdelt_rows(aoi_id: str, start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    for signal_name, query in GDELT_QUERIES[aoi_id].items():
        with_tone = signal_name == "gdelt_place_en"
        points = fetch_volraw_and_tone(query, start, end, include_tone=with_tone)
        for point in points:
            share = point["article_count"] / max(point["monitored_volume"], 1.0) * 10000.0
            rows.append({"date": point["date"], "aoi_id": aoi_id, "signal_name": signal_name, "value": share})
            if with_tone and point["tone"] is not None:
                rows.append(
                    {
                        "date": point["date"],
                        "aoi_id": aoi_id,
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


def _event_window(event: Event, cfg, start: date, end: date) -> tuple[date, date] | None:
    lead = cfg.baseline_days + cfg.embargo_days + event.search_days_before + WINDOW_PAD_DAYS
    window_start = max(start, event.event_date - timedelta(days=lead))
    window_end = min(end, event.event_date + timedelta(days=event.search_days_after + WINDOW_PAD_DAYS))
    if window_start >= window_end:
        return None
    return window_start, window_end


def build_signals(start: date, end: date, gdelt_only: bool = False) -> pd.DataFrame:
    use_gfw = not gdelt_only and token() is not None
    cfg = load_index_config()
    aois = {a.aoi_id: a for a in load_aois()}
    events = {e.aoi_id: e for e in load_events()}
    rows: list[dict] = []
    for aoi_id in GDELT_QUERIES:
        window = _event_window(events[aoi_id], cfg, start, end)
        if window is None:
            continue
        win_start, win_end = window
        rows.extend(_gdelt_rows(aoi_id, win_start, win_end))
        if use_gfw:
            rows.extend(_gfw_rows(aois[aoi_id], win_start, win_end))
    frame = pd.DataFrame(rows)
    path = data_dir("processed", "signals.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame
