from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, effective_gap_hours, register, rollback


GAP_SQL = """
with ordered as (
    select vessel_id, ts, region_id,
        lag(ts) over (partition by vessel_id order by ts) as prev_ts,
        lag(geom) over (partition by vessel_id order by ts) as prev_geom,
        geom
    from ais_position
    where vessel_id is not null
)
select vessel_id, prev_ts, ts, region_id,
    extract(epoch from (ts - prev_ts)) / 3600.0 as gap_hours,
    ST_Y(prev_geom) as lat, ST_X(prev_geom) as lon
from ordered
where prev_ts is not null and ts - prev_ts > (%s * interval '1 hour')
"""


@register("ais_gap", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    try:
        with conn.cursor() as cur:
            cur.execute(GAP_SQL, (params["min_gap_hours"],))
            gap_rows = cur.fetchall()
            cur.execute(
                "select started_at, ended_at from collector_gap "
                "where source_id = 'aisstream' order by started_at"
            )
            outages = [(row[0], row[1]) for row in cur.fetchall()]
    except psycopg.Error:
        rollback(conn)
        return []

    detections: list[Detection] = []
    for vessel_id, prev_ts, ts, region_id, gap_hours, lat, lon in gap_rows:
        eff = effective_gap_hours(prev_ts, ts, outages)
        if eff < params["min_gap_hours"]:
            continue
        detections.append(
            Detection(
                subject_type="vessel",
                subject_id=vessel_id,
                term="AIS_GAP",
                points=params["points_base"] + params["points_per_hour"] * eff,
                src_table="ais_position",
                src_id=f"{vessel_id}:{prev_ts.isoformat()}",
                detail=f"AIS gap {eff:.1f}h effective (raw {gap_hours:.1f}h)",
                lon=lon,
                lat=lat,
                ts=ts,
            )
        )
        coverage_ok = eff >= float(gap_hours) - 1e-9
        if coverage_ok:
            detections.append(
                Detection(
                    subject_type="vessel",
                    subject_id=vessel_id,
                    term="COVERAGE_OK",
                    points=params["coverage_bonus"],
                    src_table="collector_gap",
                    src_id="no_outage_overlap",
                    detail="receiver coverage confirmed during gap",
                    lon=lon,
                    lat=lat,
                    ts=ts,
                )
            )
    return detections
