from __future__ import annotations

import numpy as np
import pandas as pd

from presail.config import IndexConfig, Thresholds
from presail.index import compute_index, robust_z


def _cfg(**overrides) -> IndexConfig:
    base = dict(
        baseline_days=30,
        embargo_days=2,
        mad_floor=0.5,
        z_clip_min=0.0,
        z_clip_max=6.0,
        transform_k=1.5,
        ffill_max_days=3,
        thresholds=Thresholds(watch=65, alert=80),
        weights={"a": 0.5, "b": 0.5, "unused": 0.25},
    )
    base.update(overrides)
    return IndexConfig(**base)


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2021-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx)


def test_robust_z_flat_baseline_then_spike():
    cfg = _cfg()
    values = _series([10.0] * 40 + [40.0])
    z = robust_z(values, cfg)
    assert np.isnan(z.iloc[0])
    spike = z.iloc[-1]
    assert spike > 0
    assert spike <= cfg.z_clip_max


def test_negative_deviation_clipped_to_zero():
    cfg = _cfg()
    values = _series([10.0] * 40 + [1.0])
    z = robust_z(values, cfg)
    assert z.iloc[-1] == 0.0


def _signals_frame(values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2021-01-01", periods=len(values), freq="D").date
    rows = []
    for signal in ("a", "b"):
        for day, value in zip(dates, values):
            rows.append({"date": day.isoformat(), "aoi_id": "x", "signal_name": signal, "value": value})
    return pd.DataFrame(rows)


def test_no_lookahead_future_change_does_not_affect_past():
    cfg = _cfg()
    values = [10.0] * 40 + [12.0, 13.0, 14.0]
    base = _signals_frame(values)
    tampered_values = values[:-1] + [9999.0]
    tampered = _signals_frame(tampered_values)

    base_index, _ = compute_index(base, cfg)
    tampered_index, _ = compute_index(tampered, cfg)

    cut = base_index[base_index["date"] < "2021-02-12"].set_index("date")["index"]
    cut_tampered = tampered_index[tampered_index["date"] < "2021-02-12"].set_index("date")["index"]
    assert cut.equals(cut_tampered.loc[cut.index])


def test_transform_bounds_and_monotonic():
    cfg = _cfg()
    values = [10.0] * 40 + [10.0, 60.0]
    frame = _signals_frame(values)
    index_df, contrib_df = compute_index(frame, cfg)
    assert index_df["index"].between(0, 100).all()
    quiet = index_df[index_df["date"] == "2021-02-10"]["index"].iloc[0]
    spike = index_df["index"].max()
    assert spike > quiet


def test_contributions_sum_to_index():
    cfg = _cfg()
    values = [10.0] * 40 + [10.0, 50.0]
    frame = _signals_frame(values)
    index_df, contrib_df = compute_index(frame, cfg)
    last_day = index_df["date"].max()
    idx_value = index_df[index_df["date"] == last_day]["index"].iloc[0]
    points = contrib_df[contrib_df["date"] == last_day]["index_points"].sum()
    assert abs(points - idx_value) < 0.05


def test_weight_renormalization_single_signal():
    cfg = _cfg()
    dates = pd.date_range("2021-01-01", periods=42, freq="D").date
    values = [10.0] * 40 + [10.0, 40.0]
    rows = [
        {"date": d.isoformat(), "aoi_id": "x", "signal_name": "a", "value": v}
        for d, v in zip(dates, values)
    ]
    index_df, _ = compute_index(pd.DataFrame(rows), cfg)
    assert not index_df.empty
    assert index_df["index"].max() > 0
