from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


@register("clustering", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    start, end = window
    try:
        with conn.cursor() as cur:
            cur.execute(
                "with clustered as ("
                "  select vessel_id, region_id, ts, geom, "
                "  ST_ClusterDBSCAN(geom, eps := %s, minpoints := %s) "
                "    over (partition by coalesce(region_id, 'unknown')) as cid "
                "  from ais_position "
                "  where vessel_id is not null and ts between %s and %s"
                "), cluster_stats as ("
                "  select coalesce(region_id, 'unknown') as region_id, cid, "
                "  count(distinct vessel_id) as vessel_count, max(ts) as last_ts, "
                "  ST_X(ST_Centroid(ST_Collect(geom))) as lon, "
                "  ST_Y(ST_Centroid(ST_Collect(geom))) as lat "
                "  from clustered where cid is not null "
                "  group by coalesce(region_id, 'unknown'), cid "
                "  having count(distinct vessel_id) >= %s"
                ") "
                "select distinct c.vessel_id, s.region_id, s.cid, s.vessel_count, s.last_ts, s.lon, s.lat, "
                "exists(select 1 from zone z where z.kind = 'eez' "
                "  and z.name ilike %s and z.name not ilike %s "
                "  and ST_Contains(z.geom, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326))) as home "
                "from clustered c "
                "join cluster_stats s on coalesce(c.region_id, 'unknown') = s.region_id and c.cid = s.cid",
                (
                    params["eps_degrees"],
                    params.get("dbscan_minpoints", 3),
                    start,
                    end,
                    params["min_size"],
                    params.get("home_eez_ilike", "%korea%"),
                    params.get("home_eez_exclude_ilike", "%north%"),
                ),
            )
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    home_factor = float(params.get("home_factor", 0.35))
    return [
        Detection(
            subject_type="vessel",
            subject_id=vessel_id,
            term="clustering",
            points=params["points"] * (home_factor if home else 1.0),
            src_table="ais_position",
            src_id=f"{region_id}:cluster:{cid}",
            detail=f"cluster of {vessel_count} vessels in {region_id}"
            + (" (home waters, damped)" if home else ""),
            lon=lon,
            lat=lat,
            ts=last_ts,
        )
        for vessel_id, region_id, cid, vessel_count, last_ts, lon, lat, home in rows
    ]
