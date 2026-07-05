import os

import pytest

from mda.api import datasets
from mda.sim import presets, registry
from mda.store import pg


def test_scenario_id_validation():
    for good in ["west_sea_cable", "a", "s1", "baltic_shadow"]:
        assert registry.validate_id(good) == good
    for bad in ["", "1abc", "Bad", "a-b", "drop table", "a" * 42, "sim;drop"]:
        with pytest.raises(ValueError):
            registry.validate_id(bad)


def test_scenario_schema_name():
    assert pg.scenario_schema("west_sea_cable") == "sim_west_sea_cable"


def test_is_live():
    assert datasets.is_live(None)
    assert datasets.is_live("")
    assert datasets.is_live("live")
    assert not datasets.is_live("west_sea_cable")


def test_presets_registered():
    assert set(presets.PRESETS) == {"west_sea_cable", "baltic_shadow", "nll_intrusion"}


REQUIRED_TABLES = ["vessel", "ais_position", "alert", "alert_evidence", "osint_item", "zone", "event"]


@pytest.mark.parametrize("name", list(presets.PRESETS))
def test_preset_populates_dashboard_tables(name):
    builder_fn = presets.PRESETS[name][0]
    builder = builder_fn()
    for table in REQUIRED_TABLES:
        assert builder.rows[table], f"{name} produced no rows for {table}"
    alert_ids = {a["alert_id"] for a in builder.rows["alert"]}
    for ev in builder.rows["alert_evidence"]:
        assert ev["alert_id"] in alert_ids
    for step in builder.rows["alert_timeline_step"]:
        assert step["alert_id"] in alert_ids


@pytest.mark.parametrize("name", list(presets.PRESETS))
def test_preset_deterministic(name):
    builder_fn = presets.PRESETS[name][0]
    counts_a = {t: len(r) for t, r in builder_fn().rows.items()}
    counts_b = {t: len(r) for t, r in builder_fn().rows.items()}
    assert counts_a == counts_b


def test_ais_positions_have_valid_geom():
    builder = presets.west_sea_cable()
    for pos in builder.rows["ais_position"][:50]:
        assert pos["geom"].startswith("SRID=4326;POINT(")
        assert pos["mmsi"] is not None


@pytest.mark.skipif(not os.environ.get("MDA_PG_DSN"), reason="requires local Postgres")
def test_generate_and_query_roundtrip():
    from mda.api import queries

    sid = "test_ci_scenario"
    with pg.connect() as conn:
        pg.ensure_schema(conn)
        registry.drop_scenario(conn, sid)
        registry.create_scenario(conn, sid, "CI 테스트", kind="assumed")
        counts = presets.generate(conn, sid, "west_sea_cable")
    assert counts["vessel"] > 0
    with datasets.dataset_conn(sid) as conn:
        assert registry.scenario_exists(conn, sid)
        meta = queries.get_meta(conn, extend_to_now=False)
        assert meta["counts"]["vessel"] > 0
        start, end = queries.compute_window(conn, extend_to_now=False)
        assert start < end
        threats = queries.get_threats(conn, queries.resolve_region("west_sea"), start, end)
        assert any(t["level"] == "CRITICAL" for t in threats)
    with pg.connect() as conn:
        registry.drop_scenario(conn, sid)
