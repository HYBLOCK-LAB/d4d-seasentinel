from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mda.pipelines.scoring import METHOD, assemble, clip_score, effective_gap_hours, level_for

T0 = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
THRESHOLDS = {"high": 75.0, "critical": 90.0}


def _h(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def test_effective_gap_no_outage_is_raw():
    assert effective_gap_hours(_h(0), _h(10), []) == 10.0


def test_effective_gap_fully_covered_by_outage_is_zero():
    assert effective_gap_hours(_h(2), _h(8), [(_h(0), _h(12))]) == 0.0


def test_effective_gap_partial_overlap_subtracts_exactly():
    assert effective_gap_hours(_h(0), _h(10), [(_h(6), _h(14))]) == 6.0


def test_effective_gap_open_ended_outage_runs_to_gap_end():
    assert effective_gap_hours(_h(0), _h(10), [(_h(7), None)]) == 7.0


def test_clip_score_bounds():
    assert clip_score(-5.0) == 0.0
    assert clip_score(50.0) == 50.0
    assert clip_score(140.0) == 100.0


def test_level_for_thresholds_and_boundaries():
    assert level_for(74.9, THRESHOLDS) == "MED"
    assert level_for(75.0, THRESHOLDS) == "HIGH"
    assert level_for(89.9, THRESHOLDS) == "HIGH"
    assert level_for(90.0, THRESHOLDS) == "CRITICAL"


def test_assemble_score_is_clipped_evidence_sum_with_method_version():
    evidence = [
        {"term_name": "A", "points": 60.0, "src_table": "t", "src_id": "1", "detail": None},
        {"term_name": "B", "points": 55.0, "src_table": "t", "src_id": "2", "detail": None},
    ]
    alert = assemble({"alert_id": "x", "why": ["A", "B"]}, evidence, THRESHOLDS)
    assert alert["score"] == 100.0
    assert alert["level"] == "CRITICAL"
    assert all(e["method_version"] == METHOD for e in evidence)

    small = [{"term_name": "A", "points": 40.0, "src_table": "t", "src_id": "1", "detail": None}]
    alert2 = assemble({"alert_id": "y", "why": ["A"]}, small, THRESHOLDS)
    assert alert2["score"] == 40.0
    assert alert2["level"] == "MED"
