import hashlib
import json
from datetime import datetime, timezone

from mda.config import load_scoring_config
from mda.paths import config_path
from mda.store import pg

METHOD = "scoring.v1"

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
select distinct a.vessel_id, s.vessel_id as sanction_row_id, s.name, s.source_id
from ais_position a
join vessel av on av.vessel_id = a.vessel_id
join vessel s on s.imo = av.imo and s.source_id in ('ofac_sdn', 'un1718')
where av.imo is not null
"""


def clip_score(x: float) -> float:
    return max(0.0, min(100.0, x))


def level_for(score: float, thresholds: dict) -> str:
    if score >= thresholds["critical"]:
        return "CRITICAL"
    if score >= thresholds["high"]:
        return "HIGH"
    return "MED"


def effective_gap_hours(gap_start: datetime, gap_end: datetime, outages: list[tuple[datetime, datetime | None]]) -> float:
    raw = (gap_end - gap_start).total_seconds() / 3600.0
    overlap_total = 0.0
    for started_at, ended_at in outages:
        outage_end = ended_at if ended_at is not None else gap_end
        overlap_start = max(gap_start, started_at)
        overlap_end = min(gap_end, outage_end)
        if overlap_end > overlap_start:
            overlap_total += (overlap_end - overlap_start).total_seconds() / 3600.0
    return max(0.0, raw - overlap_total)


def assemble(alert_base: dict, evidence: list[dict], thresholds: dict) -> dict:
    for e in evidence:
        e["method_version"] = METHOD
    score = clip_score(sum(e["points"] for e in evidence))
    alert = dict(alert_base)
    alert["score"] = score
    alert["level"] = level_for(score, thresholds)
    return alert


def _alert(alert_id, alert_type, vessel_id, zone_id, region_id, title_ko, title_en, why) -> dict:
    return {
        "alert_id": alert_id,
        "alert_type": alert_type,
        "vessel_id": vessel_id,
        "zone_id": zone_id,
        "region_id": region_id,
        "generated_at": datetime.now(timezone.utc),
        "method_version": METHOD,
        "score": None,
        "level": None,
        "title_ko": title_ko,
        "title_en": title_en,
        "why": why,
        "source_id": "scoring",
        "collector": "scoring_pipeline",
        "raw_ref": None,
    }


def detect_ais_gap(conn, params: dict) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(GAP_SQL, (params["min_gap_hours"],))
        gap_rows = cur.fetchall()
        cur.execute(
            "select started_at, ended_at from collector_gap where source_id = 'aisstream' order by started_at"
        )
        outages = [(row[0], row[1]) for row in cur.fetchall()]

    threats = []
    for vessel_id, prev_ts, ts, region_id, gap_hours, lat, lon in gap_rows:
        eff = effective_gap_hours(prev_ts, ts, outages)
        if eff < params["min_gap_hours"]:
            continue
        coverage_ok = eff >= float(gap_hours) - 1e-9
        why = ["AIS_GAP"]
        evidence = [
            {
                "term_name": "AIS_GAP",
                "points": params["points_base"] + params["points_per_hour"] * eff,
                "src_table": "ais_position",
                "src_id": f"{vessel_id}:{prev_ts.isoformat()}",
                "detail": f"AIS gap {eff:.1f}h effective (raw {gap_hours:.1f}h)",
            }
        ]
        if coverage_ok:
            why.append("COVERAGE_OK")
            evidence.append(
                {
                    "term_name": "COVERAGE_OK",
                    "points": params["coverage_bonus"],
                    "src_table": "collector_gap",
                    "src_id": "no_outage_overlap",
                    "detail": "receiver coverage confirmed during gap",
                }
            )
        alert = _alert(
            alert_id=f"gap:{vessel_id}:{prev_ts.isoformat()}",
            alert_type="dark_vessel",
            vessel_id=vessel_id,
            zone_id=None,
            region_id=region_id,
            title_ko=f"AIS 공백 {eff:.1f}시간 — 다크베슬 의심",
            title_en=f"AIS gap {eff:.1f}h — possible dark vessel",
            why=why,
        )
        threats.append({"alert": alert, "evidence": evidence, "links": []})
    return threats


def detect_cable_proximity(conn, params: dict) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(CABLE_SQL, (params["max_km"] * 1000,))
        cable_rows = cur.fetchall()

    threats = []
    for vessel_id, zone_id, name, dist_m, first_ts in cable_rows:
        dist_km = dist_m / 1000.0
        why = ["CABLE_PROXIMITY"]
        evidence = [
            {
                "term_name": "CABLE_PROXIMITY",
                "points": params["points_base"] + params["points_per_km_inside"] * (params["max_km"] - dist_km),
                "src_table": "zone",
                "src_id": zone_id,
                "detail": f"{name} within {dist_km:.2f}km",
            }
        ]
        with conn.cursor() as cur:
            cur.execute(
                "select count(*), min(p.ts), max(p.ts) from ais_position p "
                "join zone z on z.zone_id = %s "
                "where p.vessel_id = %s and p.sog is not null and p.sog < %s "
                "and ST_DWithin(p.geom::geography, z.geom::geography, %s)",
                (zone_id, vessel_id, params["loiter_sog_kn"], params["max_km"] * 1000),
            )
            count, min_ts, max_ts = cur.fetchone()
        if count is not None and count >= 3:
            span_h = (max_ts - min_ts).total_seconds() / 3600.0
            if span_h >= params["loiter_min_hours"]:
                why.append("LOITERING")
                evidence.append(
                    {
                        "term_name": "LOITERING",
                        "points": params["loiter_points"],
                        "src_table": "ais_position",
                        "src_id": f"{vessel_id}:loiter",
                        "detail": f"SOG<{params['loiter_sog_kn']}kn for {span_h:.1f}h",
                    }
                )
        alert = _alert(
            alert_id=f"cable:{vessel_id}:{zone_id}",
            alert_type="zone_intrusion",
            vessel_id=vessel_id,
            zone_id=zone_id,
            region_id=None,
            title_ko=f"해저케이블 {name} {dist_km:.1f}km 근접",
            title_en=f"Subsea cable {name} proximity {dist_km:.1f}km",
            why=why,
        )
        link = {
            "link_id": f"near:{vessel_id}:{zone_id}",
            "src_type": "vessel",
            "src_id": vessel_id,
            "dst_type": "zone",
            "dst_id": zone_id,
            "rel_type": "near_cable",
            "confidence": 1.0,
            "hypothesis": False,
            "method_version": METHOD,
            "source_id": "scoring",
            "collector": "scoring_pipeline",
            "raw_ref": None,
        }
        threats.append({"alert": alert, "evidence": evidence, "links": [link]})
    return threats


def detect_sanctioned_match(conn, params: dict) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(SANCTIONED_SQL)
        rows = cur.fetchall()

    threats = []
    for vessel_id, sanction_row_id, name, source_id in rows:
        with conn.cursor() as cur:
            cur.execute("select max(ts) from ais_position where vessel_id = %s", (vessel_id,))
            ts = cur.fetchone()[0]
        why = ["SANCTIONED_MATCH", "OBSERVED_PRESENCE"]
        evidence = [
            {
                "term_name": "SANCTIONED_MATCH",
                "points": params["points_match"],
                "src_table": "vessel",
                "src_id": sanction_row_id,
                "detail": f"IMO match to {source_id} entry {name}",
            },
            {
                "term_name": "OBSERVED_PRESENCE",
                "points": params["points_presence"],
                "src_table": "ais_position",
                "src_id": f"{vessel_id}:latest",
                "detail": f"live AIS contact {ts.isoformat()}" if ts is not None else "live AIS contact unknown",
            },
        ]
        alert = _alert(
            alert_id=f"sanctioned:{vessel_id}",
            alert_type="dark_vessel",
            vessel_id=vessel_id,
            zone_id=None,
            region_id=None,
            title_ko=f"제재 선박 실시간 포착 ({source_id})",
            title_en=f"Sanctioned vessel live contact ({source_id})",
            why=why,
        )
        link = {
            "link_id": f"sanctioned_as:{vessel_id}:{sanction_row_id}",
            "src_type": "vessel",
            "src_id": vessel_id,
            "dst_type": "document",
            "dst_id": sanction_row_id,
            "rel_type": "sanctioned_as",
            "confidence": 1.0,
            "hypothesis": False,
            "method_version": METHOD,
            "source_id": "scoring",
            "collector": "scoring_pipeline",
            "raw_ref": None,
        }
        threats.append({"alert": alert, "evidence": evidence, "links": [link]})
    return threats


def apply_zone_boost(conn, threats: list[dict], params: dict) -> None:
    vessel_ids = list({t["alert"]["vessel_id"] for t in threats if t["alert"]["vessel_id"] is not None})
    if not vessel_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "select distinct p.vessel_id from ais_position p "
            "join zone z on z.kind = 'aoi' and ST_Contains(z.geom, p.geom) "
            "where p.vessel_id = any(%s)",
            (vessel_ids,),
        )
        hits = {row[0] for row in cur.fetchall()}
    if not hits:
        return
    for t in threats:
        if t["alert"]["vessel_id"] in hits:
            t["evidence"].append(
                {
                    "term_name": "ZONE_PRESENCE",
                    "points": params["boost_points"],
                    "src_table": "zone",
                    "src_id": "aoi",
                    "detail": "activity inside monitored AOI",
                }
            )
            t["alert"]["why"].append("ZONE_PRESENCE")


def run_scoring(min_gap_hours: float | None = None, cable_km: float | None = None) -> dict:
    cfg = load_scoring_config()

    gap_params = dict(cfg.detectors["ais_gap"])
    if min_gap_hours is not None:
        gap_params["min_gap_hours"] = min_gap_hours

    cable_params = dict(cfg.detectors["cable_proximity"])
    if cable_km is not None:
        cable_params["max_km"] = cable_km

    sanctioned_params = dict(cfg.detectors["sanctioned_match"])
    zone_params = dict(cfg.detectors["zone_activity"])

    with pg.connect() as conn:
        threats: list[dict] = []
        threats.extend(detect_ais_gap(conn, gap_params))
        threats.extend(detect_cable_proximity(conn, cable_params))
        threats.extend(detect_sanctioned_match(conn, sanctioned_params))
        apply_zone_boost(conn, threats, zone_params)

        alert_rows = []
        evidence_rows = []
        link_rows = []
        by_type: dict[str, int] = {}

        for t in threats:
            alert = assemble(t["alert"], t["evidence"], cfg.thresholds)
            alert_rows.append(alert)
            for e in t["evidence"]:
                e["alert_id"] = alert["alert_id"]
                evidence_rows.append(e)
            link_rows.extend(t["links"])
            by_type[alert["alert_type"]] = by_type.get(alert["alert_type"], 0) + 1

        config_hash = hashlib.sha1(config_path("scoring.yaml").read_bytes()).hexdigest()[:16]
        pg.upsert(
            conn,
            "method_registry",
            [{"method_version": METHOD, "config_snapshot": json.dumps({"config_hash": config_hash})}],
            conflict=["method_version"],
            update=["config_snapshot"],
        )

        pg.upsert(
            conn,
            "alert",
            alert_rows,
            conflict=["alert_id"],
            update=["score", "level", "generated_at", "why"],
        )

        alert_ids = [a["alert_id"] for a in alert_rows]
        with conn.cursor() as cur:
            if alert_ids:
                cur.execute("delete from alert_evidence where alert_id = any(%s)", (alert_ids,))
            if evidence_rows:
                cur.executemany(
                    "insert into alert_evidence "
                    "(alert_id, term_name, points, src_table, src_id, detail, method_version) "
                    "values (%(alert_id)s, %(term_name)s, %(points)s, %(src_table)s, %(src_id)s, %(detail)s, %(method_version)s)",
                    evidence_rows,
                )

        pg.upsert(
            conn,
            "entity_link",
            link_rows,
            conflict=["link_id"],
            update=["confidence"],
        )

    return {
        "alerts": len(alert_rows),
        "evidence": len(evidence_rows),
        "links": len(link_rows),
        "by_type": by_type,
    }
