from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


@register("course_change", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    start, end = window
    try:
        with conn.cursor() as cur:
            cur.execute(
                "with ordered as ("
                "  select vessel_id, ts, geom, sog, cog, "
                "  lag(cog) over (partition by vessel_id order by ts) as prev_cog "
                "  from ais_position "
                "  where vessel_id is not null and cog is not null and sog is not null "
                "  and ts between %s and %s"
                "), turns as ("
                "  select vessel_id, ts, geom, "
                "  least(abs(cog - prev_cog), 360.0 - abs(cog - prev_cog)) as delta "
                "  from ordered "
                "  where prev_cog is not null and sog > %s"
                ") "
                "select vessel_id, count(*), max(delta), max(ts), "
                "ST_X(ST_Centroid(ST_Collect(geom))), ST_Y(ST_Centroid(ST_Collect(geom))) "
                "from turns where delta > %s "
                "group by vessel_id",
                (start, end, params["min_sog_kn"], params["delta_degrees"]),
            )
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    detections: list[Detection] = []
    for vessel_id, count, max_delta, ts, lon, lat in rows:
        points = params["points_base"] + min(count, params["max_events"]) * params["points_per_event"]
        detections.append(
            Detection(
                subject_type="vessel",
                subject_id=vessel_id,
                term="course_change",
                points=points,
                src_table="ais_position",
                src_id=f"{vessel_id}:course_change:{ts.isoformat()}",
                detail=f"{count} course changes >{params['delta_degrees']}deg; max delta {max_delta:.1f}deg",
                lon=lon,
                lat=lat,
                ts=ts,
            )
        )
    return detections
