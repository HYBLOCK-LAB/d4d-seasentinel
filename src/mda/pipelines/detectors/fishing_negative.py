from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback, table_columns
from mda.pipelines.detectors.gfw_gap_event import _event_match_query


@register("fishing_negative", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    columns = table_columns(conn, "event")
    query_parts = _event_match_query(columns, "gfw_fishing")
    if query_parts is None:
        return []
    query, prefix_args = query_parts
    start, end = window
    time_args = (start, end) if "ts" in columns else (start.date(), end.date())
    try:
        with conn.cursor() as cur:
            cur.execute(query, prefix_args + time_args)
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    points = -abs(params["points"])
    return [
        Detection(
            subject_type="vessel",
            subject_id=vessel_id,
            term="fishing_negative",
            points=points,
            src_table="event",
            src_id=event_id,
            detail=f"GFW fishing activity matched by MMSI: {name or event_id}",
            lon=lon,
            lat=lat,
            ts=ts,
        )
        for vessel_id, event_id, name, ts, lon, lat in rows
    ]
