from __future__ import annotations

from datetime import datetime, timezone

from mda.store import pg

METHOD = "tracks.v1"

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
where prev_ts is not null and ts - prev_ts > make_interval(hours => %s)
"""

CABLE_SQL = """
select p.vessel_id, z.zone_id, z.name,
    min(ST_Distance(p.geom::geography, z.geom::geography)) as dist_m,
    min(p.ts) as first_ts
from ais_position p
join zone z on z.kind = 'cable'
where ST_DWithin(p.geom::geography, z.geom::geography, %s)
group by p.vessel_id, z.zone_id, z.name
"""

SANCTIONED_SQL = """
select distinct a.vessel_id, s.name, s.source_id
from ais_position a
join vessel av on av.vessel_id = a.vessel_id
join vessel s on s.imo = av.imo and s.source_id in ('ofac_sdn', 'un1718')
where av.imo is not null
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _alert(alert_id, alert_type, level, vessel_id, zone_id, region_id, score, title_ko, title_en, why):
    return {
        "alert_id": alert_id,
        "alert_type": alert_type,
        "level": level,
        "vessel_id": vessel_id,
        "zone_id": zone_id,
        "region_id": region_id,
        "generated_at": _now(),
        "method_version": METHOD,
        "score": score,
        "title_ko": title_ko,
        "title_en": title_en,
        "why": why,
        "source_id": "tracks",
        "collector": "tracks_analysis",
        "raw_ref": None,
    }


def detect_ais_gaps(conn, min_gap_hours: float = 6.0) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(GAP_SQL, (min_gap_hours,))
        rows = cur.fetchall()
    alerts = []
    for vessel_id, prev_ts, ts, region_id, gap_hours, lat, lon in rows:
        alert_id = f"gap:{vessel_id}:{prev_ts.isoformat()}"
        score = min(100.0, 60.0 + gap_hours)
        alerts.append(
            _alert(
                alert_id, "dark_vessel", "HIGH" if gap_hours >= 12 else "MED", vessel_id, None, region_id,
                round(score, 1),
                f"AIS 공백 {gap_hours:.1f}시간 — 다크베슬 의심",
                f"AIS gap {gap_hours:.1f}h — possible dark vessel",
                ["AIS_GAP"],
            )
        )
    return alerts


def detect_cable_proximity(conn, max_km: float = 3.0) -> tuple[list[dict], list[dict]]:
    with conn.cursor() as cur:
        cur.execute(CABLE_SQL, (max_km * 1000.0,))
        rows = cur.fetchall()
    alerts, links = [], []
    for vessel_id, zone_id, name, dist_m, first_ts in rows:
        alert_id = f"cable:{vessel_id}:{zone_id}"
        alerts.append(
            _alert(
                alert_id, "zone_intrusion", "HIGH", vessel_id, zone_id, None,
                round(min(100.0, 85.0 + (max_km - dist_m / 1000.0)), 1),
                f"해저케이블 {name} {dist_m/1000:.1f}km 근접",
                f"within {dist_m/1000:.1f}km of cable {name}",
                ["GEO_CABLE_PROXIMITY"],
            )
        )
        links.append(
            {
                "link_id": f"near:{vessel_id}:{zone_id}",
                "src_type": "vessel",
                "src_id": vessel_id,
                "dst_type": "zone",
                "dst_id": zone_id,
                "rel_type": "near_cable",
                "confidence": 1.0,
                "hypothesis": False,
                "method_version": METHOD,
                "source_id": "tracks",
                "collector": "tracks_analysis",
                "raw_ref": None,
            }
        )
    return alerts, links


def flag_sanctioned_presence(conn) -> tuple[list[dict], list[dict]]:
    with conn.cursor() as cur:
        cur.execute(SANCTIONED_SQL)
        rows = cur.fetchall()
    alerts, links = [], []
    for vessel_id, name, source_id in rows:
        alert_id = f"sanctioned:{vessel_id}"
        alerts.append(
            _alert(
                alert_id, "dark_vessel", "CRITICAL", vessel_id, None, None, 98.0,
                f"제재 선박 실시간 포착 ({source_id})",
                f"sanctioned vessel live contact ({source_id})",
                ["SANCTIONED_MATCH"],
            )
        )
        links.append(
            {
                "link_id": f"sanction:{vessel_id}",
                "src_type": "vessel",
                "src_id": vessel_id,
                "dst_type": "document",
                "dst_id": vessel_id,
                "rel_type": "sanctioned_as",
                "confidence": 1.0,
                "hypothesis": False,
                "method_version": METHOD,
                "source_id": "tracks",
                "collector": "tracks_analysis",
                "raw_ref": source_id,
            }
        )
    return alerts, links


def run_analysis(min_gap_hours: float = 6.0, cable_km: float = 3.0) -> dict:
    with pg.connect() as conn:
        gap_alerts = detect_ais_gaps(conn, min_gap_hours)
        cable_alerts, cable_links = detect_cable_proximity(conn, cable_km)
        sanction_alerts, sanction_links = flag_sanctioned_presence(conn)
        alerts = gap_alerts + cable_alerts + sanction_alerts
        links = cable_links + sanction_links
        if alerts:
            pg.upsert(conn, "alert", alerts, conflict=["alert_id"], update=["score", "level", "generated_at", "why"])
        if links:
            pg.upsert(conn, "entity_link", links, conflict=["link_id"], update=["confidence"])
    return {
        "ais_gap_alerts": len(gap_alerts),
        "cable_proximity_alerts": len(cable_alerts),
        "sanctioned_alerts": len(sanction_alerts),
        "entity_links": len(links),
    }
