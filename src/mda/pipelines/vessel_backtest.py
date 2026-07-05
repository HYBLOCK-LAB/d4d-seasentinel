from __future__ import annotations

from collections import defaultdict

from mda.config import load_scoring_config
from mda.pipelines.detectors.core import Detection
from mda.pipelines.scoring import (
    _run_detectors,
    drop_friendly_on_hard_evidence,
    merge_db_overrides,
    score_detections,
)
from mda.store import pg


def run_vessel_backtest(dataset: str, detectors: list[str] | None = None) -> dict:
    """Score a scenario schema's vessels with the live detector set (no writes)
    and grade the result against the preset's curated alerts as ground truth.

    detectors: optional subset to evaluate in isolation — useful because preset
    background fleets report at a much coarser cadence than the live AIS stream,
    which makes cadence-sensitive detectors (ais_gap) fire on every interval."""
    cfg = load_scoring_config()
    if detectors:
        for name, block in cfg.detectors.items():
            block["enabled"] = name in detectors
    with pg.connect(readonly=True, dataset=dataset) as conn:
        cfg = merge_db_overrides(conn, cfg)
        with conn.cursor() as cur:
            cur.execute("select min(ts), max(ts) from ais_position")
            start, end = cur.fetchone()
        if start is None:
            return {"dataset": dataset, "error": "no ais_position data"}

        detections, detector_counts = _run_detectors(conn, cfg, (start, end), None, None)
        grouped: dict[str, list[Detection]] = defaultdict(list)
        for d in detections:
            if d.subject_type == "vessel":
                grouped[d.subject_id].append(d)

        scored: dict[str, dict] = {}
        for vessel_id, dets in grouped.items():
            dets = drop_friendly_on_hard_evidence(dets)
            score, level = score_detections(dets, cfg.thresholds)
            scored[vessel_id] = {
                "score": round(score, 1),
                "level": level,
                "terms": sorted({d.term for d in dets if d.points > 0}),
            }

        with conn.cursor() as cur:
            cur.execute("select distinct vessel_id from alert where vessel_id is not null")
            truth = {row[0] for row in cur.fetchall()}

    min_alert = float(cfg.thresholds.get("min_alert", 0.0))
    predicted = {v for v, s in scored.items() if s["score"] >= min_alert}
    tp = sorted(predicted & truth)
    fp = sorted(predicted - truth)
    fn = sorted(truth - predicted)
    return {
        "dataset": dataset,
        "window": [start.isoformat(), end.isoformat()],
        "vessels_scored": len(scored),
        "detectors": detector_counts,
        "truth_threats": sorted(truth),
        "predicted": {
            v: scored[v] for v in sorted(predicted, key=lambda v: -scored[v]["score"])
        },
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(len(tp) / len(predicted), 3) if predicted else None,
        "recall": round(len(tp) / len(truth), 3) if truth else None,
    }
