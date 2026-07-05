from __future__ import annotations

from datetime import datetime, timezone

from mda.pipelines import exporter


def test_alert_evidence_rows_group_by_alert():
    rows = [
        ("a1", "AIS_GAP", 30.0, "ais_position", "p1", "gap detected"),
        ("a2", "ZONE_ENTRY", 12.5, "zone", "z1", None),
    ]

    grouped = exporter._evidence_by_alert(rows)

    assert grouped["a1"] == [
        {
            "term": "AIS_GAP",
            "points": 30.0,
            "src_table": "ais_position",
            "src_id": "p1",
            "detail": "gap detected",
        }
    ]
    assert grouped["a2"][0]["term"] == "ZONE_ENTRY"


def test_alert_timeline_rows_group_by_alert_and_serialize_ts():
    rows = [
        ("a1", 1, "detect", datetime(2026, 7, 4, 1, 2, 3, tzinfo=timezone.utc), "found"),
        ("a1", 2, "score", None, "scored"),
    ]

    grouped = exporter._timeline_by_alert(rows)

    assert grouped["a1"] == [
        {"step_no": 1, "phase": "detect", "ts": "2026-07-04T01:02:03Z", "description": "found"},
        {"step_no": 2, "phase": "score", "ts": None, "description": "scored"},
    ]


def test_alert_rows_to_json_uses_resolved_region_and_preserves_contract_keys():
    rows = [
        (
            "a1",
            None,
            "v1",
            80.0,
            "HIGH",
            "한국어",
            "English",
            "dark_vessel",
            ["AIS_GAP"],
            "west_sea",
            None,
        )
    ]
    evidence = {"a1": [{"term": "AIS_GAP", "points": 30.0, "src_table": "ais_position", "src_id": "p1", "detail": "gap"}]}
    timeline = {"a1": [{"step_no": 1, "phase": "detect", "ts": "2026-07-04T01:02:03Z", "description": "found"}]}

    alerts = exporter._alert_rows_to_json(rows, "east_sea", evidence, timeline)

    assert alerts == [
        {
            "id": "a1",
            "region": "west_sea",
            "vessel": "v1",
            "score": 80.0,
            "level": "HIGH",
            "title_ko": "한국어",
            "title_en": "English",
            "category": "dark_vessel",
            "signals": ["AIS_GAP"],
            "why": ["AIS_GAP"],
            "evidence": evidence["a1"],
            "timeline": timeline["a1"],
            "propagation": [],
        }
    ]


def test_alert_rows_to_json_prefers_requested_region_when_inferred_regions_conflict():
    rows = [
        (
            "a1",
            None,
            "v1",
            80.0,
            "HIGH",
            "한국어",
            "English",
            "dark_vessel",
            [],
            "east_sea",
            "west_sea",
        )
    ]

    alerts = exporter._alert_rows_to_json(rows, "west_sea", {}, {})

    assert alerts[0]["region"] == "west_sea"
