from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


def crossing_points(origin_north_deg: float, southing_deg: float, params: dict) -> float | None:
    if origin_north_deg < params["origin_min_deg"]:
        return None
    if southing_deg < params["southward_min_deg"]:
        return None
    return min(
        float(params["max_points"]),
        float(params["points_base"]) + float(params["points_per_deg"]) * southing_deg,
    )


@register("geofence_crossing", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    start, end = window
    try:
        with conn.cursor() as cur:
            cur.execute(
                "with trk as ("
                "  select vessel_id,"
                "    ST_MakeLine(geom order by ts) as track,"
                "    (array_agg(geom order by ts asc))[1] as first_geom,"
                "    (array_agg(ST_Y(geom) order by ts asc))[1] as first_lat,"
                "    (array_agg(ST_Y(geom) order by ts desc))[1] as last_lat,"
                "    (array_agg(ST_X(geom) order by ts desc))[1] as last_lon,"
                "    max(ts) as last_ts"
                "  from ais_position"
                "  where vessel_id is not null and ts between %s and %s"
                "  group by vessel_id having count(*) >= 2"
                ") "
                "select t.vessel_id, z.zone_id, z.name,"
                "  ST_Y(t.first_geom) - ST_Y(ST_ClosestPoint(z.geom, t.first_geom)),"
                "  t.first_lat - t.last_lat, t.last_lon, t.last_lat, t.last_ts "
                "from trk t "
                "join zone z on z.kind = 'geofence_line' and ST_Intersects(t.track, z.geom)",
                (start, end),
            )
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    detections: list[Detection] = []
    for vessel_id, zone_id, name, origin_north, southing, last_lon, last_lat, last_ts in rows:
        points = crossing_points(float(origin_north), float(southing), params)
        if points is None:
            continue
        detections.append(
            Detection(
                subject_type="vessel",
                subject_id=vessel_id,
                term="geofence_crossing",
                points=points,
                src_table="zone",
                src_id=f"{vessel_id}:{zone_id}",
                detail=(
                    f"crossed {name or zone_id} southbound: origin {origin_north:.2f}deg "
                    f"north of line, net southing {southing:.2f}deg"
                ),
                lon=last_lon,
                lat=last_lat,
                ts=last_ts,
            )
        )
    return detections
