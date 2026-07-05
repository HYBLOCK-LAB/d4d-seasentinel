from __future__ import annotations

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


SANCTIONED_SQL = """
select distinct a.vessel_id, s.vessel_id as sanction_row_id, s.name, s.source_id
from ais_position a
join vessel av on av.vessel_id = a.vessel_id
join vessel s on s.imo = av.imo and s.source_id in ('ofac_sdn', 'un1718')
where av.imo is not null
"""


@register("sanctioned_match", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    try:
        with conn.cursor() as cur:
            cur.execute(SANCTIONED_SQL)
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    detections: list[Detection] = []
    for vessel_id, sanction_row_id, name, source_id in rows:
        try:
            with conn.cursor() as cur:
                cur.execute("select max(ts) from ais_position where vessel_id = %s", (vessel_id,))
                ts = cur.fetchone()[0]
        except psycopg.Error:
            rollback(conn)
            ts = None
        detections.extend(
            [
                Detection(
                    subject_type="vessel",
                    subject_id=vessel_id,
                    term="SANCTIONED_MATCH",
                    points=params["points_match"],
                    src_table="vessel",
                    src_id=sanction_row_id,
                    detail=f"IMO match to {source_id} entry {name}",
                    ts=ts,
                ),
                Detection(
                    subject_type="vessel",
                    subject_id=vessel_id,
                    term="OBSERVED_PRESENCE",
                    points=params["points_presence"],
                    src_table="ais_position",
                    src_id=f"{vessel_id}:latest",
                    detail=f"live AIS contact {ts.isoformat()}" if ts is not None else "live AIS contact unknown",
                    ts=ts,
                ),
            ]
        )
    return detections
