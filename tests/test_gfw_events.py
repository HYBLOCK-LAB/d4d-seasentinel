from __future__ import annotations

from datetime import date

from mda.collectors.gfw_events import _event_row, _signal_rows
from mda.config import Aoi, Region


FIXTURE_PAGE = {
    "metadata": {"datasets": ["public-global-port-visits-events:v4.0"]},
    "limit": 1,
    "offset": 0,
    "nextOffset": None,
    "total": 1,
    "entries": [
        {
            "start": "2026-06-25T03:10:00.000Z",
            "end": "2026-06-25T08:30:00.000Z",
            "id": "abc123",
            "type": "port_visit",
            "position": {"lat": 18.5, "lon": 110.2},
            "vessel": {"ssvid": "412345678", "name": "TEST VESSEL", "flag": "CHN"},
        }
    ],
}


def test_event_row_maps_gfw_port_visit_fixture():
    regions = [Region(region_id="south_china_sea", name="SCS", bbox=[109.0, 9.5, 118.0, 19.6])]
    row, mmsi = _event_row(FIXTURE_PAGE["entries"][0], "port", regions)

    assert row["event_id"] == "gfw:port:abc123"
    assert row["event_type"] == "gfw_port_visit"
    assert row["event_date"] == date(2026, 6, 25)
    assert row["region_id"] == "south_china_sea"
    assert row["geom"] == "SRID=4326;POINT(110.2 18.5)"
    assert mmsi == 412345678


def test_signal_rows_use_date_aoi_signal_key_and_zero_fill():
    aoi = Aoi(
        aoi_id="hainan_staging",
        name="Hainan",
        role="staging",
        region_id="south_china_sea",
        bbox=[109.3, 18.0, 111.0, 19.6],
    )
    rows = _signal_rows(FIXTURE_PAGE["entries"], [aoi], date(2026, 6, 25), date(2026, 6, 26))

    assert [(r["date"], r["aoi_id"], r["signal_name"], r["value"]) for r in rows] == [
        (date(2026, 6, 25), "hainan_staging", "gfw_port_visit_count", 1.0),
        (date(2026, 6, 26), "hainan_staging", "gfw_port_visit_count", 0.0),
    ]
