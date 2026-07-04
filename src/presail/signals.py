from __future__ import annotations

from datetime import date

import pandas as pd

from presail.config import Aoi, load_aois
from presail.gdelt import fetch_volraw_and_tone
from presail.gfw import fetch_4wings_daily, token
from presail.paths import data_dir

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


def build_signals(start: date, end: date, gdelt_only: bool = False) -> pd.DataFrame:
    use_gfw = not gdelt_only and token() is not None
    aois = {a.aoi_id: a for a in load_aois()}
    rows: list[dict] = []
    for aoi_id in GDELT_QUERIES:
        rows.extend(_gdelt_rows(aoi_id, start, end))
        if use_gfw:
            rows.extend(_gfw_rows(aois[aoi_id], start, end))
    frame = pd.DataFrame(rows)
    path = data_dir("processed", "signals.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame
