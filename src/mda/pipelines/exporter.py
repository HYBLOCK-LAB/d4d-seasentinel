from __future__ import annotations

import json
from datetime import date, datetime, timezone

from mda.config import load_regions
from mda.paths import config_path, repo_root
from mda.store import pg

MAX_VESSELS = 800
MAX_POINTS = 400


def _iso_utc(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return value.isoformat()


def _regions_json() -> dict:
    regions = {}
    for r in load_regions():
        min_lon, min_lat, max_lon, max_lat = r.bbox
        regions[r.region_id] = {
            "id": r.region_id,
            "name_ko": r.name,
            "name_en": r.name,
            "bbox": r.bbox,
            "center": [round((min_lon + max_lon) / 2, 3), round((min_lat + max_lat) / 2, 3)],
            "theatre": r.theatre,
        }
    return {"regions": regions, "geofences": _geofences()}


def _geofences() -> list:
    with pg.connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute("select zone_id, name, kind, region_id, ST_AsGeoJSON(geom) from zone where kind like 'geofence%'")
        return [
            {"id": zid, "name": name, "kind": kind, "region": region, "geometry": json.loads(gj)}
            for zid, name, kind, region, gj in cur.fetchall()
        ]


def _coast_json() -> dict:
    path = config_path("coast.json")
    return json.loads(path.read_text()) if path.exists() else {}


def _vessels_and_tracks(region_id: str, start: datetime, end: datetime):
    with pg.connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select p.vessel_id, count(*) as n
            from ais_position p
            where p.region_id = %s and p.ts between %s and %s and p.vessel_id is not null
            group by p.vessel_id order by n desc limit %s
            """,
            (region_id, start, end, MAX_VESSELS),
        )
        vessel_ids = [r[0] for r in cur.fetchall()]
        if not vessel_ids:
            return [], {}
        cur.execute(
            "select vessel_id, mmsi, imo, name, vessel_type, length_m, owner from vessel where vessel_id = any(%s)",
            (vessel_ids,),
        )
        meta = {r[0]: r for r in cur.fetchall()}
        sanctioned = _sanctioned_ids(conn, vessel_ids)
        vessels = []
        for vid in vessel_ids:
            m = meta.get(vid, (vid, None, None, None, None, None, None))
            vessels.append(
                {
                    "id": vid,
                    "mmsi": str(m[1]) if m[1] else None,
                    "imo": m[2],
                    "name_en": m[3],
                    "name_ko": m[3],
                    "flag": None,
                    "type": m[4] or "unknown",
                    "region": region_id,
                    "length_m": m[5],
                    "threat": "sanctions_listed" if vid in sanctioned else None,
                    "flag_history": [],
                    "aliases": [],
                    "owner": m[6],
                    "note": None,
                    "mismatch": False,
                }
            )
        tracks = {}
        for vid in vessel_ids:
            cur.execute(
                """
                select ts, ST_X(geom), ST_Y(geom), sog, cog from ais_position
                where vessel_id = %s and ts between %s and %s order by ts limit %s
                """,
                (vid, start, end, MAX_POINTS),
            )
            tracks[vid] = [
                {"t": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "lon": lon, "lat": lat, "sog": sog, "cog": cog}
                for ts, lon, lat, sog, cog in cur.fetchall()
            ]
    return vessels, tracks


def _sanctioned_ids(conn, vessel_ids) -> set:
    with conn.cursor() as cur:
        cur.execute(
            """
            select av.vessel_id from vessel av
            join vessel s on s.imo = av.imo and s.source_id in ('ofac_sdn','un1718')
            where av.vessel_id = any(%s) and av.imo is not null
            """,
            (vessel_ids,),
        )
        return {r[0] for r in cur.fetchall()}


def _osint_json(region_id: str) -> list:
    with pg.connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select item_id, ts, region_id, kind, lang, text, source_module, sentiment, weight
            from osint_item
            where region_id = %s or region_id is null
            order by ts desc
            limit 200
            """,
            (region_id,),
        )
        return [
            {
                "id": iid,
                "t": _iso_utc(ts),
                "region": region or region_id,
                "kind": kind,
                "lang": lang,
                "text": text,
                "source": module,
                "entities": [],
                "sentiment": sentiment,
                "weight": weight,
            }
            for iid, ts, region, kind, lang, text, module, sentiment, weight in cur.fetchall()
        ]


def _evidence_by_alert(rows: list[tuple]) -> dict[str, list[dict]]:
    evidence: dict[str, list[dict]] = {}
    for alert_id, term_name, points, src_table, src_id, detail in rows:
        evidence.setdefault(alert_id, []).append(
            {
                "term": term_name,
                "points": points,
                "src_table": src_table,
                "src_id": src_id,
                "detail": detail,
            }
        )
    return evidence


def _timeline_by_alert(rows: list[tuple]) -> dict[str, list[dict]]:
    timeline: dict[str, list[dict]] = {}
    for alert_id, step_no, phase, ts, description in rows:
        timeline.setdefault(alert_id, []).append(
            {
                "step_no": step_no,
                "phase": phase,
                "ts": _iso_utc(ts),
                "description": description,
            }
        )
    return timeline


def _resolved_alert_region(default_region: str, alert_region: str | None, zone_region: str | None, vessel_region: str | None) -> str:
    if alert_region:
        return alert_region
    if zone_region == default_region or vessel_region == default_region:
        return default_region
    return zone_region or vessel_region or default_region


def _alert_rows_to_json(rows: list[tuple], region_id: str, evidence: dict[str, list[dict]], timeline: dict[str, list[dict]]) -> list:
    alerts = []
    for aid, region, vessel, score, level, tko, ten, atype, why, zone_region, vessel_region in rows:
        alerts.append(
            {
                "id": aid,
                "region": _resolved_alert_region(region_id, region, zone_region, vessel_region),
                "vessel": vessel,
                "score": score,
                "level": level,
                "title_ko": tko,
                "title_en": ten,
                "category": atype,
                "signals": why or [],
                "why": why or [],
                "evidence": evidence.get(aid, []),
                "timeline": timeline.get(aid, []),
                "propagation": [],
            }
        )
    return alerts


def _alerts_json(region_id: str) -> list:
    with pg.connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select
                a.alert_id,
                a.region_id,
                a.vessel_id,
                a.score,
                a.level,
                a.title_ko,
                a.title_en,
                a.alert_type,
                a.why,
                z.region_id as zone_region_id,
                vp.region_id as vessel_region_id
            from alert a
            left join zone z on z.zone_id = a.zone_id
            left join lateral (
                select p.region_id
                from ais_position p
                where p.vessel_id = a.vessel_id and p.region_id is not null
                order by p.ts desc
                limit 1
            ) vp on true
            where
                a.region_id = %s
                or (
                    a.region_id is null
                    and (
                        z.region_id = %s
                        or vp.region_id = %s
                        or (z.region_id is null and vp.region_id is null)
                    )
                )
            order by a.generated_at desc
            limit 200
            """,
            (region_id, region_id, region_id),
        )
        rows = cur.fetchall()
        alert_ids = [row[0] for row in rows]
        if not alert_ids:
            return []
        cur.execute(
            """
            select alert_id, term_name, points, src_table, src_id, detail
            from alert_evidence
            where alert_id = any(%s)
            order by alert_id, points desc
            """,
            (alert_ids,),
        )
        evidence = _evidence_by_alert(cur.fetchall())
        cur.execute(
            """
            select alert_id, step_no, phase, ts, description
            from alert_timeline_step
            where alert_id = any(%s)
            order by alert_id, step_no
            """,
            (alert_ids,),
        )
        timeline = _timeline_by_alert(cur.fetchall())
        return _alert_rows_to_json(rows, region_id, evidence, timeline)


def _graph_json(vessel_ids: list) -> dict:
    with pg.connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute(
            "select link_id, src_type, src_id, dst_type, dst_id, rel_type, hypothesis from entity_link limit 500"
        )
        edges, node_ids = [], set()
        for _, st, sid, dt, did, rel, hyp in cur.fetchall():
            edges.append({"source": sid, "target": did, "rel": rel, "hypothesis": hyp})
            node_ids.add((sid, st))
            node_ids.add((did, dt))
        nodes = [{"id": nid, "label": nid, "type": ntype, "meta": {}} for nid, ntype in node_ids]
    return {"nodes": nodes, "edges": edges}


def _infrastructure_json(region_id: str) -> dict:
    with pg.connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute(
            "select zone_id, name, ST_AsGeoJSON(geom) from zone where kind='cable' limit 300"
        )
        cables = []
        for zid, name, gj in cur.fetchall():
            geom = json.loads(gj)
            coords = geom.get("coordinates") or []
            path = coords[0] if geom.get("type") == "MultiLineString" and coords else coords
            cables.append({"id": zid, "name": name, "region": region_id, "owners": [], "path": path, "criticality": "high", "note": None})
        r = {rr.region_id: rr.bbox for rr in load_regions()}.get(region_id)
        ports = []
        if r:
            cur.execute(
                "select facility_id, name, ST_X(geom), ST_Y(geom), country from facility where kind='port' and ST_Within(geom, ST_MakeEnvelope(%s,%s,%s,%s,4326)) limit 200",
                (r[0], r[1], r[2], r[3]),
            )
            ports = [{"id": fid, "name": name, "lonlat": [lon, lat], "country": country} for fid, name, lon, lat, country in cur.fetchall()]
    return {"cables": cables, "structures": [], "ports": ports}


def _counts() -> dict:
    tables = ["vessel", "ais_position", "sar_detection", "osint_item", "alert", "zone", "facility", "event", "document", "weather_daily"]
    with pg.connect(readonly=True) as conn, conn.cursor() as cur:
        counts = {}
        for t in tables:
            cur.execute(f"select count(*) from {t}")
            counts[t] = cur.fetchone()[0]
    return counts


def export_dashboard(region_id: str, start: datetime, end: datetime, out_dir=None) -> dict:
    out = out_dir or (repo_root() / "dashboard" / "data")
    out.mkdir(parents=True, exist_ok=True)
    span = end - start
    with pg.connect(readonly=True) as conn, conn.cursor() as cur:
        cur.execute("select max(ts) from ais_position where region_id = %s", (region_id,))
        latest = cur.fetchone()[0]
    if latest and latest < end:
        end = latest
        start = end - span
    vessels, tracks = _vessels_and_tracks(region_id, start, end)
    vessel_ids = [v["id"] for v in vessels]
    files = {
        "regions": _regions_json(),
        "coast": _coast_json(),
        "vessels": vessels,
        "tracks": tracks,
        "sar": [],
        "osint": _osint_json(region_id),
        "infrastructure": _infrastructure_json(region_id),
        "alerts": _alerts_json(region_id),
        "graph": _graph_json(vessel_ids),
        "meta": {
            "generated_for": "MDA ontology — real-data export",
            "region": region_id,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "counts": {
                "vessels": len(vessels),
                "ais_points": sum(len(t) for t in tracks.values()),
                "sar_detections": 0,
                "sar_mismatch": 0,
                "osint": None,
            },
            "ontology_counts": _counts(),
            "sources": ["aisstream", "gfw", "gdelt", "stealthmole", "open_meteo", "ofac_sdn", "un1718", "world_port_index", "telegeography_cables"],
            "gaps": ["sar per-detection feed not yet integrated (sar empty)", "NLL geofence has no authoritative public coordinates"],
        },
    }
    files["meta"]["counts"]["osint"] = len(files["osint"])
    for name, payload in files.items():
        (out / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False))
    return {"region": region_id, "vessels": len(vessels), "osint": len(files["osint"]), "alerts": len(files["alerts"]), "out": str(out)}
