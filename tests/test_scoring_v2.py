from __future__ import annotations

from mda.config import ScoringConfig, load_scoring_config
from mda.pipelines.detectors.core import Detection
from mda.pipelines.detectors.geofence_crossing import crossing_points
from mda.pipelines.detectors.low_density import span_bucket
from mda.pipelines.detectors.north_origin import is_north_origin
from mda.pipelines.detectors.zone_anomaly import _points_for_axis
from mda.pipelines.scoring import (
    alert_type_for_subject,
    detector_params,
    detector_weight,
    drop_friendly_on_hard_evidence,
    enabled_detector_names,
    level_for,
    make_dedupe_key,
    score_detections,
)


THRESHOLDS = {"high": 75.0, "critical": 90.0}


def _d(term: str, points: float) -> Detection:
    return Detection(
        subject_type="vessel",
        subject_id="v1",
        term=term,
        points=points,
        detail="detail",
        src_table="ais_position",
        src_id="src",
    )


def test_score_detections_allows_negative_terms_before_clipping():
    score, level = score_detections([_d("gfw_gap_event", 80.0), _d("fishing_negative", -25.0)], THRESHOLDS)
    assert score == 55.0
    assert level == "MED"

    clipped, clipped_level = score_detections([_d("fishing_negative", -25.0)], THRESHOLDS)
    assert clipped == 0.0
    assert clipped_level == "MED"


def test_alert_type_and_dedupe_key_are_subject_stable():
    alert_type = alert_type_for_subject("zone")
    assert alert_type == "precursor"
    assert make_dedupe_key(alert_type, "aoi:scarborough") == "precursor:aoi:scarborough"
    assert alert_type_for_subject("vessel") == "vessel_threat"


def test_detector_config_parsing_strips_runner_keys():
    raw = {"enabled": True, "weight": 0.5, "points": 10.0}
    assert detector_weight(raw) == 0.5
    assert detector_params(raw) == {"points": 10.0}


def test_scoring_yaml_uses_v2_detector_shape():
    cfg = load_scoring_config()
    assert "gfw_gap_event" in enabled_detector_names(cfg)
    assert "zone_anomaly" in enabled_detector_names(cfg)
    for name in enabled_detector_names(cfg):
        assert "enabled" in cfg.detectors[name]
        assert "weight" in cfg.detectors[name]


def test_disabled_or_unknown_detectors_are_not_enabled():
    cfg = ScoringConfig(
        thresholds=THRESHOLDS,
        detectors={
            "loitering": {"enabled": False, "weight": 1.0, "points": 1.0},
            "unknown": {"enabled": True, "weight": 1.0},
        },
    )
    assert enabled_detector_names(cfg) == []


def test_north_origin_helper_requires_northern_start_and_southward_motion():
    assert is_north_origin(38.55, 37.9, "west_sea", 38.6, 0.3, 38.5, 0.5)
    assert is_north_origin(18.1, 17.4, "south_china_sea", 19.6, 0.3, 38.5, 0.5) is False
    assert is_north_origin(38.55, 38.2, "west_sea", 38.6, 0.3, 38.5, 0.5) is False


def test_low_density_span_buckets():
    assert span_bucket(1.5) == "short"
    assert span_bucket(12.0) == "day"
    assert span_bucket(30.0) == "multi_day"


def test_zone_axis_points_are_clipped_by_axis_config():
    params = {"axes": {"zone_gfw_gap_events_z": {"points_per_z": 6.0, "max_points": 20.0}}}
    assert _points_for_axis(params, "zone_gfw_gap_events_z", 2.0) == 12.0
    assert _points_for_axis(params, "zone_gfw_gap_events_z", 10.0) == 20.0


def test_level_for_adds_low_tier_below_low_threshold():
    thresholds = {"high": 75.0, "critical": 90.0, "low": 40.0}
    assert level_for(20.0, thresholds) == "LOW"
    assert level_for(40.0, thresholds) == "MED"
    assert level_for(75.0, thresholds) == "HIGH"
    # Configs without a "low" key keep the historical MED floor.
    assert level_for(0.0, {"high": 75.0, "critical": 90.0}) == "MED"


def test_geofence_crossing_separates_intrusion_from_clutter():
    params = {
        "origin_min_deg": 0.2,
        "southward_min_deg": 0.3,
        "points_base": 40.0,
        "points_per_deg": 10.0,
        "max_points": 60.0,
    }
    # sim_v_intr1 profile: deep northern origin, sustained southing.
    assert crossing_points(0.68, 0.74, params) == 47.4
    # Fleet clutter: origin on the line, shallow oscillation.
    assert crossing_points(0.02, 0.10, params) is None
    assert crossing_points(0.68, 0.10, params) is None
    assert crossing_points(0.5, 5.0, params) == 60.0


def test_friendly_flag_dropped_when_hard_evidence_present():
    friendly = _d("friendly_flag", -25.0)
    crossing = _d("geofence_crossing", 47.0)
    kept = drop_friendly_on_hard_evidence([friendly, crossing])
    assert [d.term for d in kept] == ["geofence_crossing"]
    # Without hard evidence the mitigating term still applies.
    soft = _d("loitering", 18.0)
    assert drop_friendly_on_hard_evidence([friendly, soft]) == [friendly, soft]
