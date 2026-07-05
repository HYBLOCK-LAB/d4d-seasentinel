from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


@register("friendly_flag", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    start, end = window
    mids = [str(m) for m in params.get("mids", [440, 441])]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select distinct vessel_id, left(mmsi::text, 3) as mid "
                "from ais_position "
                "where vessel_id is not null and ts between %s and %s "
                "and left(mmsi::text, 3) = any(%s)",
                (start, end, mids),
            )
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    points = float(params.get("points", -25.0))
    return [
        Detection(
            subject_type="vessel",
            subject_id=vessel_id,
            term="friendly_flag",
            points=points,
            src_table="vessel",
            src_id=vessel_id,
            detail=f"ROK-flagged vessel (MMSI MID {mid})",
            lon=None,
            lat=None,
            ts=None,
        )
        for vessel_id, mid in rows
    ]
