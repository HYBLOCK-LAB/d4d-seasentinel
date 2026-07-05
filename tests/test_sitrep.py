from datetime import datetime, timedelta, timezone

from mda.api import sitrep

NOW = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)


def test_generate_when_no_previous():
    assert sitrep.should_generate(None, None, "sig-a", NOW) is True


def test_generate_after_report_interval():
    prev_at = NOW - sitrep.REPORT_INTERVAL
    assert sitrep.should_generate(prev_at, "sig-a", "sig-a", NOW) is True


def test_generate_on_change_after_min_interval():
    prev_at = NOW - sitrep.MIN_INTERVAL
    assert sitrep.should_generate(prev_at, "sig-a", "sig-b", NOW) is True


def test_hold_on_change_within_min_interval():
    prev_at = NOW - (sitrep.MIN_INTERVAL - timedelta(seconds=1))
    assert sitrep.should_generate(prev_at, "sig-a", "sig-b", NOW) is False


def test_hold_when_unchanged_within_interval():
    prev_at = NOW - timedelta(minutes=30)
    assert sitrep.should_generate(prev_at, "sig-a", "sig-a", NOW) is False


def test_threat_signature_order_independent():
    a = [{"id": "x", "level": "HIGH"}, {"id": "y", "level": "MED"}]
    b = [{"id": "y", "level": "MED"}, {"id": "x", "level": "HIGH"}]
    assert sitrep.threat_signature(a) == sitrep.threat_signature(b)


def test_threat_signature_reflects_level_change():
    a = [{"id": "x", "level": "HIGH"}, {"id": "y", "level": "MED"}]
    c = [{"id": "x", "level": "CRITICAL"}, {"id": "y", "level": "MED"}]
    assert sitrep.threat_signature(a) != sitrep.threat_signature(c)
