from __future__ import annotations

from datetime import datetime, timezone

from psycopg.rows import dict_row

from mda.store import pg
from mda.sync import foundry_mappings as fm
from mda.sync.foundry_client import FoundryClient

BOUNDED_QUERIES = {
    "Vessel": (
        "select * from vessel where vessel_id in "
        "(select distinct vessel_id from ais_position where vessel_id is not null) "
        "or source_id in ('ofac_sdn','un1718')",
        "vessel_id",
        fm.vessel_object,
    ),
    "Event": ("select * from event", "event_id", fm.event_object),
    "Alert": ("select * from alert", "alert_id", fm.alert_object),
    "Document": (
        "select document_id, doc_type, title, lang, url, source_id, raw_ref from document where doc_type='sanctions_entry'",
        "document_id",
        fm.document_object,
    ),
    "IndexDaily": ("select * from index_daily", "aoi_id_date", fm.index_daily_object),
}


def _rows(conn, query: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        return cur.fetchall()


def sync_bounded() -> dict:
    client = FoundryClient()
    results = {}
    with pg.connect() as conn:
        for object_type, (query, pk, mapper) in BOUNDED_QUERIES.items():
            rows = _rows(conn, query)
            objects = [mapper(r) for r in rows]
            results[object_type] = client.upsert(object_type, pk, objects)
        pg.upsert(
            conn,
            "foundry_sync_state",
            [{"object_type": ot, "last_synced_at": datetime.now(timezone.utc)} for ot in BOUNDED_QUERIES],
            conflict=["object_type"],
            update=["last_synced_at"],
        )
    results["configured"] = client.configured()
    return results
