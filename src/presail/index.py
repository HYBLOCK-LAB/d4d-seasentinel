from __future__ import annotations

import numpy as np
import pandas as pd

from presail.config import IndexConfig

MIN_BASELINE_POINTS = 30


def _mad(window: np.ndarray) -> float:
    return float(np.median(np.abs(window - np.median(window))))


def robust_z(values: pd.Series, cfg: IndexConfig) -> pd.Series:
    baseline = values.shift(cfg.embargo_days)
    median = baseline.rolling(cfg.baseline_days, min_periods=MIN_BASELINE_POINTS).median()
    mad = baseline.rolling(cfg.baseline_days, min_periods=MIN_BASELINE_POINTS).apply(_mad, raw=True)
    scale = (1.4826 * mad).clip(lower=cfg.mad_floor)
    z = (values - median) / scale
    return z.clip(lower=cfg.z_clip_min, upper=cfg.z_clip_max)


def _level(index_value: float, cfg: IndexConfig) -> str:
    if index_value >= cfg.thresholds.alert:
        return "ALERT"
    if index_value >= cfg.thresholds.watch:
        return "WATCH"
    return "NONE"


def compute_index(signals: pd.DataFrame, cfg: IndexConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    signals = signals.copy()
    signals["date"] = pd.to_datetime(signals["date"])
    index_rows = []
    contrib_rows = []

    for aoi_id, group in signals.groupby("aoi_id"):
        wide = group.pivot_table(index="date", columns="signal_name", values="value")
        wide = wide.asfreq("D")
        full_index = wide.index

        z_clipped = {}
        for signal_name in wide.columns:
            weight = cfg.weights.get(signal_name)
            if weight is None:
                continue
            series = wide[signal_name].fillna(0.0)
            z_clipped[signal_name] = robust_z(series, cfg)

        for day in full_index:
            weighted_sum = 0.0
            weight_total = 0.0
            day_contrib = []
            for signal_name, z_series in z_clipped.items():
                z_value = z_series.get(day)
                if z_value is None or np.isnan(z_value):
                    continue
                weight = cfg.weights[signal_name]
                contribution = weight * float(z_value)
                weighted_sum += contribution
                weight_total += weight
                day_contrib.append((signal_name, float(z_value), contribution))
            if weight_total == 0.0:
                continue
            raw_score = weighted_sum / weight_total
            index_value = 100.0 * (1.0 - np.exp(-raw_score / cfg.transform_k))
            index_rows.append(
                {
                    "date": day.date().isoformat(),
                    "aoi_id": aoi_id,
                    "index": round(index_value, 2),
                    "raw_score": round(raw_score, 4),
                    "level": _level(index_value, cfg),
                }
            )
            for signal_name, z_value, contribution in day_contrib:
                points = index_value * contribution / weighted_sum if weighted_sum > 0 else 0.0
                contrib_rows.append(
                    {
                        "date": day.date().isoformat(),
                        "aoi_id": aoi_id,
                        "signal_name": signal_name,
                        "z_clip": round(z_value, 4),
                        "index_points": round(points, 3),
                    }
                )

    return pd.DataFrame(index_rows), pd.DataFrame(contrib_rows)
