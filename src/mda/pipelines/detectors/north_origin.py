from __future__ import annotations

import psycopg

from mda.config import load_regions
from mda.pipelines.detectors.core import Detection, Window, register, rollback


def is_north_origin(
    first_lat: float,
    last_lat: float,
    region_id: str | None,
    north_edge: float | None,
    edge_margin_deg: float,
    west_sea_north_lat: float,
    southward_min_deg: float,
) -> bool:
    near_region_edge = north_edge is not None and first_lat >= north_edge - edge_margin_deg
    west_sea_override = region_id == "west_sea" and first_lat >= west_sea_north_lat
    return (near_region_edge or west_sea_override) and (first_lat - last_lat) >= southward_min_deg


@register("north_origin", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    start, end = window
    try:
        with conn.cursor() as cur:
            cur.execute(
                "with first_fix as ("
                "  select distinct on (vessel_id) vessel_id, ts, region_id, ST_X(geom) as lon, ST_Y(geom) as lat "
                "  from ais_position where vessel_id is not null and ts between %s and %s "
                "  order by vessel_id, ts asc"
                "), last_fix as ("
                "  select distinct on (vessel_id) vessel_id, ts, region_id, ST_X(geom) as lon, ST_Y(geom) as lat "
                "  from ais_position where vessel_id is not null and ts between %s and %s "
                "  order by vessel_id, ts desc"
                ") "
                "select f.vessel_id, f.ts, f.region_id, f.lon, f.lat, l.ts, l.region_id, l.lon, l.lat "
                "from first_fix f join last_fix l on l.vessel_id = f.vessel_id",
                (start, end, start, end),
            )
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    north_edges = {r.region_id: r.bbox[3] for r in load_regions()}
    detections: list[Detection] = []
    for vessel_id, first_ts, first_region, first_lon, first_lat, last_ts, last_region, last_lon, last_lat in rows:
        region_id = first_region or last_region
        if not is_north_origin(
            first_lat=first_lat,
            last_lat=last_lat,
            region_id=region_id,
            north_edge=north_edges.get(region_id),
            edge_margin_deg=params["edge_margin_deg"],
            west_sea_north_lat=params["west_sea_north_lat"],
            southward_min_deg=params["southward_min_deg"],
        ):
            continue
        detections.append(
            Detection(
                subject_type="vessel",
                subject_id=vessel_id,
                term="north_origin",
                points=params["points"],
                src_table="ais_position",
                src_id=f"{vessel_id}:north_origin:{first_ts.isoformat()}",
                detail=(
                    f"first fix lat {first_lat:.3f} near north edge, then moved south "
                    f"{first_lat - last_lat:.3f}deg"
                ),
                lon=last_lon,
                lat=last_lat,
                ts=last_ts,
            )
        )
    return detections
