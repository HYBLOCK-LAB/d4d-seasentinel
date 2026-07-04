from __future__ import annotations

import math

from mda.store.migrate_legacy import _bbox_ewkt, _clean, _signal_source


def test_bbox_ewkt_is_closed_ring_with_srid():
    ewkt = _bbox_ewkt([124.0, 34.5, 126.6, 38.6])
    assert ewkt.startswith("SRID=4326;POLYGON((")
    coords = ewkt.split("((")[1].rstrip("))").split(", ")
    assert len(coords) == 5
    assert coords[0] == coords[-1]
    assert coords[0] == "124.0 34.5"


def test_signal_source_mapping():
    assert _signal_source("gfw_presence_hours") == "gfw"
    assert _signal_source("gdelt_place_en") == "gdelt"
    assert _signal_source("mystery") == "unknown"


def test_clean_nan_becomes_none():
    assert _clean(float("nan")) is None
    assert _clean(None) is None
    assert _clean(3.5) == 3.5
    assert not math.isnan(_clean(0.0))
