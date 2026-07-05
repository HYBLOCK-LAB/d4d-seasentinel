from mda.api import assess


def test_action_points_mapping():
    assert assess.ACTION_POINTS["dismiss"] == -40.0
    assert assess.ACTION_POINTS["lower"] == -20.0
    assert assess.ACTION_POINTS["raise"] == 15.0


def test_clip_score_bounds():
    assert assess.clip_score(-12.0) == 0.0
    assert assess.clip_score(55.5) == 55.5
    assert assess.clip_score(140.0) == 100.0


def test_resolve_level_thresholds():
    thresholds = {"high": 75.0, "critical": 90.0}
    assert assess.resolve_level(95.0, thresholds) == "CRITICAL"
    assert assess.resolve_level(90.0, thresholds) == "CRITICAL"
    assert assess.resolve_level(80.0, thresholds) == "HIGH"
    assert assess.resolve_level(30.0, thresholds) == "MED"
