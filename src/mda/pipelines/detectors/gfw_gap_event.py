from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback, table_columns


def _event_match_query(columns: set[str], event_type: str) -> tuple[str, tuple] | None:
    if "mmsi" in columns:
        join_sql = "join vessel v on v.mmsi is not null and v.mmsi::text = e.mmsi::text"
        subject_sql = "v.vessel_id"
    elif "vessel_id" in columns:
        join_sql = "join vessel v on v.vessel_id = e.vessel_id"
        subject_sql = "v.vessel_id"
    else:
        return None

    ts_sql = "e.ts" if "ts" in columns else "e.event_date::timestamptz"
    time_clause = "e.ts between %s and %s" if "ts" in columns else "e.event_date between %s and %s"
    geom_sql = "ST_X(e.geom), ST_Y(e.geom)" if "geom" in columns else "null::double precision, null::double precision"
    query = (
        f"select {subject_sql}, e.event_id, e.name, {ts_sql}, {geom_sql} "
        f"from event e {join_sql} "
        f"where e.event_type = %s and {time_clause}"
    )
    return query, (event_type,)


@register("gfw_gap_event", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    columns = table_columns(conn, "event")
    query_parts = _event_match_query(columns, "gfw_gap")
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

    return [
        Detection(
            subject_type="vessel",
            subject_id=vessel_id,
            term="gfw_gap_event",
            points=params["points"],
            src_table="event",
            src_id=event_id,
            detail=f"GFW gap event matched by MMSI: {name or event_id}",
            lon=lon,
            lat=lat,
            ts=ts,
        )
        for vessel_id, event_id, name, ts, lon, lat in rows
    ]
