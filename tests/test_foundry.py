from __future__ import annotations

from datetime import date, datetime, timezone

from mda.sync import foundry_mappings as fm
from mda.sync.foundry_client import FoundryClient


def test_vessel_object_maps_keys():
    obj = fm.vessel_object({"vessel_id": "imo:123", "mmsi": 44, "imo": 123, "name": "X", "vessel_type": "tanker", "length_m": 100.0, "owner": "Y", "source_id": "ofac_sdn"})
    assert obj["vessel_id"] == "imo:123"
    assert obj["imo"] == 123


def test_event_object_serializes_date():
    obj = fm.event_object({"event_id": "e1", "name": "n", "event_type": "t", "event_date": date(2024, 8, 31), "region_id": "west_sea", "description": "d", "citations": ["u"]})
    assert obj["event_date"] == "2024-08-31"
    assert obj["region_id"] == "west_sea"


def test_index_daily_composite_key():
    obj = fm.index_daily_object({"aoi_id": "sabina_shoal", "date": date(2024, 8, 1), "index_value": 78.2, "level": "WATCH", "method_version": "index.v1"})
    assert obj["aoi_id_date"] == "sabina_shoal|2024-08-01|index.v1"
    assert obj["index_value"] == 78.2


def test_alert_object_maps_optional_dashboard_fields():
    obj = fm.alert_object(
        {
            "alert_id": "a1",
            "alert_type": "dark_vessel",
            "level": "MED",
            "generated_at": datetime(2026, 7, 4, 1, 2, 3, tzinfo=timezone.utc),
            "score": 75.5,
            "why": ("AIS_GAP", "ZONE_ENTRY"),
            "title_ko": "제목",
            "summary_ko": "요약",
            "dedupe_key": "dark:v1",
        }
    )
    assert obj["why"] == ["AIS_GAP", "ZONE_ENTRY"]
    assert obj["title_ko"] == "제목"
    assert obj["summary_ko"] == "요약"
    assert obj["dedupe_key"] == "dark:v1"


def test_alert_object_tolerates_missing_optional_dashboard_fields():
    obj = fm.alert_object({"alert_id": "a1", "generated_at": None})
    assert obj["why"] == []
    assert obj["title_ko"] is None
    assert obj["summary_ko"] is None
    assert obj["dedupe_key"] is None


def test_client_dry_run_without_credentials():
    client = FoundryClient()
    client.host, client.token = None, None
    result = client.upsert("Vessel", "vessel_id", [{"vessel_id": "a"}, {"vessel_id": "b"}])
    assert result["mode"] == "dry_run"
    assert result["planned"] == 2
