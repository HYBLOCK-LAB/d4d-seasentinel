from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


@register("zone_activity", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select distinct p.vessel_id, z.zone_id, z.name, max(p.ts), "
                "ST_X(ST_Centroid(ST_Collect(p.geom))), ST_Y(ST_Centroid(ST_Collect(p.geom))) "
                "from ais_position p "
                "join zone z on z.kind = 'aoi' and ST_Contains(z.geom, p.geom) "
                "where p.vessel_id is not null "
                "group by p.vessel_id, z.zone_id, z.name"
            )
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    return [
        Detection(
            subject_type="vessel",
            subject_id=vessel_id,
            term="ZONE_PRESENCE",
            points=params["boost_points"],
            src_table="zone",
            src_id=zone_id,
            detail=f"activity inside monitored AOI {name or zone_id}",
            lon=lon,
            lat=lat,
            ts=ts,
        )
        for vessel_id, zone_id, name, ts, lon, lat in rows
    ]
