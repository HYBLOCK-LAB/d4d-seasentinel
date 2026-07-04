from __future__ import annotations

from datetime import timezone

from mda.collectors.aisstream_realtime import _parse_ts, _position_row, _region_of, _vessel_row

_LOOKUP = {"west_sea": (124.0, 34.5, 126.6, 38.6)}

_POSITION_MSG = {
    "MessageType": "PositionReport",
    "MetaData": {"MMSI": 440123456, "latitude": 37.0, "longitude": 125.5, "time_utc": "2026-07-04 09:15:30.000000000 +0000 UTC"},
    "Message": {"PositionReport": {"Sog": 12.3, "Cog": 88.0, "TrueHeading": 90, "NavigationalStatus": 0}},
}

_STATIC_MSG = {
    "MessageType": "ShipStaticData",
    "MetaData": {"MMSI": 440123456, "ShipName": "TEST VESSEL"},
    "Message": {"ShipStaticData": {"ImoNumber": 9111222, "Name": "TEST VESSEL", "Type": 70, "Dimension": {"A": 100, "B": 50, "C": 10, "D": 10}}},
}


def test_region_of_inside_and_outside():
    assert _region_of(125.5, 37.0, _LOOKUP) == "west_sea"
    assert _region_of(140.0, 37.0, _LOOKUP) is None


def test_parse_ts_utc():
    ts = _parse_ts("2026-07-04 09:15:30.000000000 +0000 UTC")
    assert ts.tzinfo == timezone.utc
    assert (ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second) == (2026, 7, 4, 9, 15, 30)


def test_position_row_maps_fields_and_geom():
    row = _position_row(_POSITION_MSG, "PositionReport", _LOOKUP)
    assert row["mmsi"] == 440123456
    assert row["vessel_id"] == "mmsi:440123456"
    assert row["geom"] == "SRID=4326;POINT(125.5 37.0)"
    assert row["sog"] == 12.3
    assert row["region_id"] == "west_sea"


def test_vessel_row_length_from_dimensions():
    row = _vessel_row(_STATIC_MSG, "ShipStaticData")
    assert row["imo"] == 9111222
    assert row["length_m"] == 150.0
    assert row["name"] == "TEST VESSEL"
