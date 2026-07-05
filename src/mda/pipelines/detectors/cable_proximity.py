from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


CABLE_SQL = """
select p.vessel_id, z.zone_id, z.name,
    min(ST_Distance(p.geom::geography, z.geom::geography)) as dist_m,
    min(p.ts) as first_ts
from ais_position p
join zone z on z.kind = 'cable'
where ST_DWithin(p.geom::geography, z.geom::geography, %s)
group by p.vessel_id, z.zone_id, z.name
"""


@register("cable_proximity", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    try:
        with conn.cursor() as cur:
            cur.execute(CABLE_SQL, (params["max_km"] * 1000,))
            cable_rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    detections: list[Detection] = []
    for vessel_id, zone_id, name, dist_m, first_ts in cable_rows:
        dist_km = dist_m / 1000.0
        detections.append(
            Detection(
                subject_type="vessel",
                subject_id=vessel_id,
                term="CABLE_PROXIMITY",
                points=params["points_base"]
                + params["points_per_km_inside"] * (params["max_km"] - dist_km),
                src_table="zone",
                src_id=zone_id,
                detail=f"{name} within {dist_km:.2f}km",
                ts=first_ts,
            )
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select count(*), min(p.ts), max(p.ts) from ais_position p "
                    "join zone z on z.zone_id = %s "
                    "where p.vessel_id = %s and p.sog is not null and p.sog < %s "
                    "and ST_DWithin(p.geom::geography, z.geom::geography, %s)",
                    (zone_id, vessel_id, params["loiter_sog_kn"], params["max_km"] * 1000),
                )
                count, min_ts, max_ts = cur.fetchone()
        except psycopg.Error:
            rollback(conn)
            continue
        if count is not None and count >= 3:
            span_h = (max_ts - min_ts).total_seconds() / 3600.0
            if span_h >= params["loiter_min_hours"]:
                detections.append(
                    Detection(
                        subject_type="vessel",
                        subject_id=vessel_id,
                        term="LOITERING",
                        points=params["loiter_points"],
                        src_table="ais_position",
                        src_id=f"{vessel_id}:loiter",
                        detail=f"SOG<{params['loiter_sog_kn']}kn for {span_h:.1f}h",
                        ts=max_ts,
                    )
                )
    return detections
