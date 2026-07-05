from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


@register("loitering", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    start, end = window
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select vessel_id, count(*), min(ts), max(ts), "
                "ST_X(ST_Centroid(ST_Collect(geom))), ST_Y(ST_Centroid(ST_Collect(geom))) "
                "from ais_position "
                "where vessel_id is not null and sog is not null and sog <= %s "
                "and ts between %s and %s "
                "group by vessel_id "
                "having count(*) >= %s and max(ts) - min(ts) >= (%s * interval '1 hour')",
                (
                    params["sog_kn"],
                    start,
                    end,
                    params.get("min_points", 3),
                    params["min_hours"],
                ),
            )
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    detections: list[Detection] = []
    for vessel_id, count, min_ts, max_ts, lon, lat in rows:
        span_h = (max_ts - min_ts).total_seconds() / 3600.0
        detections.append(
            Detection(
                subject_type="vessel",
                subject_id=vessel_id,
                term="loitering",
                points=params["points"],
                src_table="ais_position",
                src_id=f"{vessel_id}:loitering:{min_ts.isoformat()}",
                detail=f"SOG<={params['sog_kn']}kn for {span_h:.1f}h across {count} fixes",
                lon=lon,
                lat=lat,
                ts=max_ts,
            )
        )
    return detections
