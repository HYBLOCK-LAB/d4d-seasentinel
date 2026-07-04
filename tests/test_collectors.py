from __future__ import annotations

from datetime import timezone

from mda.collectors.reference import _IMO_RE, _blank, _multiline_ewkt
from mda.collectors.stealthmole import _rows, _to_ts
from mda.collectors.weather_openmeteo import _center


def test_weather_center_is_bbox_midpoint():
    lat, lon = _center([124.0, 34.5, 126.6, 38.6])
    assert lat == 36.55
    assert lon == 125.3


def test_stealthmole_to_ts_from_unix():
    ts = _to_ts(1751622930)
    assert ts.tzinfo == timezone.utc
    assert ts.year == 2025


def test_stealthmole_rows_shape_and_ids_match():
    item = {"id": "abc123", "value": "선원 모집 서해", "createDate": 1751622930}
    osint, doc = _rows("선원 모집", "ko", "crew_recruitment", "telegram.message", item)
    assert osint["item_id"] == doc["document_id"] == "stealthmole:tt:telegram.message:abc123"
    assert osint["source_module"] == "stealthmole_tt"
    assert osint["kind"] == "crew_recruitment"
    assert doc["doc_type"] == "telegram.message"


def test_ofac_blank_sentinel():
    assert _blank("-0-") is None
    assert _blank("  ") is None
    assert _blank(" Panama ") == "Panama"


def test_imo_extraction_from_remarks():
    assert _IMO_RE.search("Vessel Registration Identification IMO 9187629; MMSI ...").group(1) == "9187629"
    assert _IMO_RE.search("... IMO number: 5936312").group(1) == "5936312"


def test_cable_multiline_ewkt():
    ewkt = _multiline_ewkt({"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]})
    assert ewkt == "SRID=4326;MULTILINESTRING((1.0 2.0, 3.0 4.0))"
    assert _multiline_ewkt({"type": "Point", "coordinates": [1, 2]}) is None
