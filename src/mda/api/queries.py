import json
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg
from psycopg import errors, sql
import yaml

from mda.config import load_aois, load_regions
from mda.paths import config_path

COUNT_TABLES = [
    "vessel",
    "ais_position",
    "alert",
    "osint_item",
    "zone",
    "facility",
    "event",
    "document",
    "signal_daily",
    "index_daily",
]

ONTOLOGY_WHITELIST = [
    "vessel",
    "ais_position",
    "alert",
    "alert_evidence",
    "osint_item",
    "event",
    "document",
    "zone",
    "facility",
    "signal_daily",
    "index_daily",
    "index_contribution",
    "weather_daily",
    "entity_link",
    "sar_detection",
    "backtest_result",
    "source",
    "method_registry",
    "collector_gap",
    "threat_score_history",
]

ORDER_PRIORITY = ("ts", "generated_at", "published_at", "fetched_at", "date")

INDEX_METHOD = "index.v1"

PK_COLUMNS = {
    "vessel": "vessel_id",
    "zone": "zone_id",
}

SRC_SUMMARY_COLUMNS = {
    "vessel": ("name", "mmsi", "imo", "source_id"),
    "zone": ("name", "kind"),
}


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _iso_utc(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        value = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    return value.isoformat()


@lru_cache(maxsize=1)
def _terms_ko() -> dict:
    try:
        with config_path("terms_ko.yaml").open() as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    return data.get("terms", {})


def _term_ko(term: str) -> str | None:
    return _terms_ko().get(term)


def _score_trend(conn, dedupe_key: str | None) -> list:
    if not dedupe_key:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ts, score FROM threat_score_history WHERE dedupe_key = %s "
                "ORDER BY ts DESC LIMIT 10",
                (dedupe_key,),
            )
            rows = cur.fetchall()
    except (errors.UndefinedTable, errors.UndefinedColumn):
        conn.rollback()
        return []
    return [{"ts": _iso(ts), "score": score} for ts, score in reversed(rows)]


def _regions_by_id() -> dict:
    return {r.region_id: r for r in load_regions()}


def default_region_id(regions: dict) -> str:
    if "west_sea" in regions:
        return "west_sea"
    return next(iter(regions))


def data_default_region(conn, regions: dict) -> str:
    # Land on the region that actually holds data in the active dataset so a
    # scenario scoped to a non-default region (e.g. baltic_shadow) is not empty.
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT region_id FROM ais_position WHERE region_id IS NOT NULL "
                "GROUP BY region_id ORDER BY count(*) DESC LIMIT 1"
            )
            row = cur.fetchone()
    except Exception:
        conn.rollback()
        row = None
    if row and row[0] in regions:
        return row[0]
    return default_region_id(regions)


def resolve_region(region_id: str | None):
    regions = _regions_by_id()
    if region_id and region_id in regions:
        return regions[region_id]
    return regions[default_region_id(regions)]


def _region_to_dict(region) -> dict:
    return {
        "id": region.region_id,
        "name": region.name,
        "bbox": list(region.bbox),
        "theatre": region.theatre,
        "priority": region.priority,
    }


def _bbox_params(region) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = region.bbox
    return min_lon, min_lat, max_lon, max_lat


def check_db(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False


def compute_window(conn, extend_to_now: bool = True) -> tuple[datetime, datetime]:
    end_expr = "coalesce((SELECT max(ts) FROM ais_position), now())"
    if extend_to_now:
        end_expr = f"greatest({end_expr}, now())"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT least("
            "  coalesce((SELECT min(ts) FROM ais_position), now()),"
            "  coalesce((SELECT min(event_date)::timestamptz FROM event), now()),"
            "  coalesce((SELECT min(date)::timestamptz FROM index_daily), now())"
            f"), {end_expr}"
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        end = datetime.now(timezone.utc)
        return end - timedelta(hours=72), end
    return row[0], row[1]


def get_window(conn, extend_to_now: bool = True) -> dict:
    start, end = compute_window(conn, extend_to_now)
    return {"start": _iso(start), "end": _iso(end)}


def get_counts(conn) -> dict:
    counts = {}
    for table in COUNT_TABLES:
        query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        with conn.cursor() as cur:
            cur.execute(query)
            counts[table] = cur.fetchone()[0]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT mmsi) FROM ais_position "
            "WHERE ts > now() - interval '10 minutes'"
        )
        counts["vessel_active_10m"] = cur.fetchone()[0]
    return counts


def get_changes(conn, region) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              (
                SELECT ts FROM ais_position
                WHERE region_id = %(region_id)s
                ORDER BY ts DESC
                LIMIT 1
              ) AS ais_max_ts,
              (
                SELECT count(*) FROM ais_position
                WHERE region_id = %(region_id)s
                  AND ts > now() - interval '1 hour'
              ) AS ais_rows_1h,
              (
                SELECT generated_at FROM alert
                ORDER BY generated_at DESC
                LIMIT 1
              ) AS alerts_max_ts,
              (
                SELECT event_date::timestamptz FROM event
                ORDER BY event_date DESC
                LIMIT 1
              ) AS events_max_ts,
              (
                SELECT ts FROM osint_item
                ORDER BY ts DESC
                LIMIT 1
              ) AS osint_max_ts,
              (
                SELECT count(DISTINCT mmsi) FROM ais_position
                WHERE region_id = %(region_id)s
                  AND ts > now() - interval '10 minutes'
              ) AS active_vessels_10m
            """,
            {"region_id": region.region_id},
        )
        row = cur.fetchone()
    (
        ais_max_ts,
        ais_rows_1h,
        alerts_max_ts,
        events_max_ts,
        osint_max_ts,
        active_vessels_10m,
    ) = row
    return {
        "ais_max_ts": _iso_utc(ais_max_ts),
        "ais_rows_1h": ais_rows_1h,
        "alerts_max_ts": _iso_utc(alerts_max_ts),
        "events_max_ts": _iso_utc(events_max_ts),
        "osint_max_ts": _iso_utc(osint_max_ts),
        "active_vessels_10m": active_vessels_10m,
    }


def get_sources(conn) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT source_id FROM source ORDER BY source_id")
        rows = cur.fetchall()
    return [row[0] for row in rows]


def get_meta(conn, extend_to_now: bool = True) -> dict:
    regions = _regions_by_id()
    return {
        "regions": [_region_to_dict(region) for region in regions.values()],
        "default_region": data_default_region(conn, regions),
        "window": get_window(conn, extend_to_now),
        "counts": get_counts(conn),
        "sources": get_sources(conn),
    }


def _last_position(conn, vessel_id, start: datetime | None, end: datetime | None):
    with conn.cursor() as cur:
        row = None
        if start is not None and end is not None:
            cur.execute(
                "SELECT ST_X(geom), ST_Y(geom) FROM ais_position "
                "WHERE vessel_id = %s AND ts BETWEEN %s AND %s "
                "ORDER BY ts DESC LIMIT 1",
                (vessel_id, start, end),
            )
            row = cur.fetchone()
        if row is None:
            cur.execute(
                "SELECT ST_X(geom), ST_Y(geom) FROM ais_position "
                "WHERE vessel_id = %s ORDER BY ts DESC LIMIT 1",
                (vessel_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def _get_vessel_threats(conn, region, start: datetime, end: datetime) -> list:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT alert_id, alert_type, level, score, title_ko, title_en, "
                "region_id, vessel_id, generated_at, summary_ko, dedupe_key FROM alert "
                "WHERE (region_id = %s OR region_id IS NULL) AND vessel_id IS NOT NULL",
                (region.region_id,),
            )
            rows = cur.fetchall()
    except errors.UndefinedColumn:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT alert_id, alert_type, level, score, title_ko, title_en, "
                "region_id, vessel_id, generated_at, null::text, null::text FROM alert "
                "WHERE region_id = %s OR region_id IS NULL",
                (region.region_id,),
            )
            rows = cur.fetchall()
    threats = []
    for (
        alert_id,
        alert_type,
        level,
        score,
        title_ko,
        title_en,
        region_id,
        vessel_id,
        generated_at,
        summary_ko,
        dedupe_key,
    ) in rows:
        lon, lat = (None, None)
        if vessel_id is not None:
            lon, lat = _last_position(conn, vessel_id, start, end)
        threats.append(
            {
                "id": alert_id,
                "kind": "vessel",
                "type": alert_type,
                "level": level,
                "score": score,
                "title_ko": title_ko,
                "title_en": title_en,
                "region": region_id,
                "vessel_id": vessel_id,
                "generated_at": _iso(generated_at),
                "lon": lon,
                "lat": lat,
                "summary_ko": summary_ko,
                "trend": _score_trend(conn, dedupe_key),
            }
        )
    return threats


def _get_zone_alert_threats(conn, region, start: datetime, end: datetime) -> list:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT a.alert_id, a.alert_type, a.level, a.score, a.title_ko, a.title_en, "
                "coalesce(a.region_id, z.region_id) as region_id, a.zone_id, a.generated_at, "
                "a.summary_ko, a.dedupe_key, ST_X(ST_Centroid(z.geom)), ST_Y(ST_Centroid(z.geom)) "
                "FROM alert a LEFT JOIN zone z ON z.zone_id = a.zone_id "
                "WHERE a.zone_id IS NOT NULL AND a.vessel_id IS NULL "
                "AND (coalesce(a.region_id, z.region_id) = %s OR coalesce(a.region_id, z.region_id) IS NULL)",
                (region.region_id,),
            )
            rows = cur.fetchall()
    except errors.UndefinedColumn:
        conn.rollback()
        return []
    threats = []
    for (
        alert_id,
        alert_type,
        level,
        score,
        title_ko,
        title_en,
        region_id,
        zone_id,
        generated_at,
        summary_ko,
        dedupe_key,
        lon,
        lat,
    ) in rows:
        threat = {
            "id": alert_id,
            "kind": "zone",
            "type": alert_type,
            "level": level,
            "score": score,
            "title_ko": title_ko,
            "title_en": title_en,
            "region": region_id,
            "zone_id": zone_id,
            "generated_at": _iso(generated_at),
            "lon": lon,
            "lat": lat,
            "summary_ko": summary_ko,
            "trend": _score_trend(conn, dedupe_key),
        }
        if zone_id and zone_id.startswith("aoi:"):
            threat["aoi_id"] = zone_id[4:]
        threats.append(threat)
    return threats


def _get_area_threats(conn, region, start: datetime, end: datetime) -> list:
    region_aois = [a.aoi_id for a in load_aois() if a.region_id == region.region_id]
    if not region_aois:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT aoi_id, date, level, index_value FROM index_daily "
            "WHERE level != 'NONE' AND method_version = %s AND date BETWEEN %s AND %s "
            "AND aoi_id = ANY(%s)",
            (INDEX_METHOD, start.date(), end.date(), region_aois),
        )
        rows = cur.fetchall()
    threats = []
    for aoi_id, threat_date, level, index_value in rows:
        threats.append(
            {
                "id": f"area:{aoi_id}:{threat_date.isoformat()}",
                "kind": "area",
                "type": "escalation_index",
                "level": level,
                "score": index_value,
                "title_ko": f"{aoi_id} 사전징후 지수 {level}",
                "title_en": f"{aoi_id} pre-sail index {level}",
                "aoi_id": aoi_id,
                "date": _iso(threat_date),
                "summary_ko": None,
                "trend": [],
            }
        )
    return threats


def get_threats(conn, region, start: datetime, end: datetime) -> list:
    threats = (
        _get_vessel_threats(conn, region, start, end)
        + _get_zone_alert_threats(conn, region, start, end)
        + _get_area_threats(conn, region, start, end)
    )
    threats.sort(key=lambda t: t["score"] or 0, reverse=True)
    return threats


def _resolve_src_summary(conn, src_table: str, src_id):
    columns = SRC_SUMMARY_COLUMNS.get(src_table)
    if columns is None:
        return None
    pk_column = PK_COLUMNS[src_table]
    query = sql.SQL("SELECT {} FROM {} WHERE {} = %s").format(
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.Identifier(src_table),
        sql.Identifier(pk_column),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(query, (src_id,))
            row = cur.fetchone()
    except psycopg.Error:
        conn.rollback()
        return None
    if row is None:
        return None
    return dict(zip(columns, row))


def _resolve_provenance(conn, src_table: str, src_id):
    pk_column = PK_COLUMNS.get(src_table, f"{src_table}_id")
    query = sql.SQL(
        "SELECT source_id, collector, fetched_at, raw_ref FROM {} WHERE {} = %s"
    ).format(sql.Identifier(src_table), sql.Identifier(pk_column))
    try:
        with conn.cursor() as cur:
            cur.execute(query, (src_id,))
            row = cur.fetchone()
    except psycopg.Error:
        conn.rollback()
        return None
    if row is None:
        return None
    source_id, collector, fetched_at, raw_ref = row
    return {
        "source_id": source_id,
        "collector": collector,
        "fetched_at": _iso(fetched_at),
        "raw_ref": raw_ref,
    }


def _get_alert_evidence(conn, alert_id) -> list:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT term_name, points, detail, src_table, src_id "
                "FROM alert_evidence WHERE alert_id = %s ORDER BY points DESC",
                (alert_id,),
            )
            rows = cur.fetchall()
    except errors.UndefinedTable:
        conn.rollback()
        return []
    evidence = []
    for term_name, points, detail, src_table, src_id in rows:
        evidence.append(
            {
                "term": term_name,
                "term_ko": _term_ko(term_name),
                "points": points,
                "detail": detail,
                "src_table": src_table,
                "src_id": src_id,
                "src_summary": (
                    _resolve_src_summary(conn, src_table, src_id) if src_table else None
                ),
                "provenance": (
                    _resolve_provenance(conn, src_table, src_id) if src_table else None
                ),
            }
        )
    return evidence


def _get_vessel_threat_evidence(conn, threat_id: str):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT alert_id, alert_type, level, score, title_ko, title_en, "
                "region_id, vessel_id, zone_id, generated_at, summary_ko, dedupe_key FROM alert WHERE alert_id = %s",
                (threat_id,),
            )
            row = cur.fetchone()
    except errors.UndefinedColumn:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT alert_id, alert_type, level, score, title_ko, title_en, "
                "region_id, vessel_id, null::text, generated_at, null::text, null::text FROM alert WHERE alert_id = %s",
                (threat_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    (
        alert_id,
        alert_type,
        level,
        score,
        title_ko,
        title_en,
        region_id,
        vessel_id,
        zone_id,
        generated_at,
        summary_ko,
        dedupe_key,
    ) = row
    lon, lat = (None, None)
    if vessel_id is not None:
        lon, lat = _last_position(conn, vessel_id, None, None)
    elif zone_id is not None:
        with conn.cursor() as cur:
            cur.execute("SELECT ST_X(ST_Centroid(geom)), ST_Y(ST_Centroid(geom)) FROM zone WHERE zone_id = %s", (zone_id,))
            zrow = cur.fetchone()
        if zrow is not None:
            lon, lat = zrow
    threat = {
        "id": alert_id,
        "kind": "zone" if vessel_id is None and zone_id is not None else "vessel",
        "type": alert_type,
        "level": level,
        "score": score,
        "title_ko": title_ko,
        "title_en": title_en,
        "region": region_id,
        "generated_at": _iso(generated_at),
        "lon": lon,
        "lat": lat,
        "summary_ko": summary_ko,
        "trend": _score_trend(conn, dedupe_key),
    }
    if vessel_id is not None:
        threat["vessel_id"] = vessel_id
    if zone_id is not None:
        threat["zone_id"] = zone_id
        if zone_id.startswith("aoi:"):
            threat["aoi_id"] = zone_id[4:]
    return {"threat": threat, "evidence": _get_alert_evidence(conn, alert_id)}


def _fetch_signal_daily(conn, aoi_id: str, threat_date: date, signal_name: str):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value, source_id, collector, fetched_at, raw_ref "
                "FROM signal_daily WHERE aoi_id = %s AND date = %s AND signal_name = %s "
                "AND method_version = %s",
                (aoi_id, threat_date, signal_name, INDEX_METHOD),
            )
            row = cur.fetchone()
    except errors.UndefinedColumn:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM signal_daily "
                "WHERE aoi_id = %s AND date = %s AND signal_name = %s",
                (aoi_id, threat_date, signal_name),
            )
            row = cur.fetchone()
        if row is None:
            return None, None
        return {"value": row[0]}, None
    if row is None:
        return None, None
    value, source_id, collector, fetched_at, raw_ref = row
    return {"value": value}, {
        "source_id": source_id,
        "collector": collector,
        "fetched_at": _iso(fetched_at),
        "raw_ref": raw_ref,
    }


def _get_area_evidence(conn, aoi_id: str, threat_date: date) -> list:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT signal_name, index_points, z_clip FROM index_contribution "
                "WHERE aoi_id = %s AND date = %s AND method_version = %s "
                "ORDER BY index_points DESC",
                (aoi_id, threat_date, INDEX_METHOD),
            )
            rows = cur.fetchall()
    except errors.UndefinedTable:
        conn.rollback()
        return []
    evidence = []
    for signal_name, index_points, z_clip in rows:
        src_summary, provenance = _fetch_signal_daily(
            conn, aoi_id, threat_date, signal_name
        )
        evidence.append(
            {
                "term": signal_name,
                "term_ko": _term_ko(signal_name),
                "points": index_points,
                "detail": f"z={z_clip}",
                "src_table": "signal_daily",
                "src_id": f"{aoi_id}:{threat_date.isoformat()}:{signal_name}",
                "src_summary": src_summary,
                "provenance": provenance,
            }
        )
    return evidence


def _get_area_threat_evidence(conn, threat_id: str):
    parts = threat_id.split(":", 2)
    if len(parts) != 3:
        return None
    _, aoi_id, date_str = parts
    try:
        threat_date = date.fromisoformat(date_str)
    except ValueError:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT level, index_value FROM index_daily "
            "WHERE aoi_id = %s AND date = %s AND method_version = %s",
            (aoi_id, threat_date, INDEX_METHOD),
        )
        row = cur.fetchone()
    if row is None:
        return None
    level, index_value = row
    threat = {
        "id": threat_id,
        "kind": "area",
        "type": "escalation_index",
        "level": level,
        "score": index_value,
        "title_ko": f"{aoi_id} 사전징후 지수 {level}",
        "title_en": f"{aoi_id} pre-sail index {level}",
        "aoi_id": aoi_id,
        "date": _iso(threat_date),
        "summary_ko": None,
        "trend": [],
    }
    return {"threat": threat, "evidence": _get_area_evidence(conn, aoi_id, threat_date)}


def get_threat_evidence(conn, threat_id: str):
    if threat_id.startswith("area:"):
        return _get_area_threat_evidence(conn, threat_id)
    return _get_vessel_threat_evidence(conn, threat_id)


def explain_threat(conn, threat_id: str) -> dict | None:
    result = get_threat_evidence(conn, threat_id)
    if result is None or result["threat"].get("kind") == "area":
        return None
    evidence = [
        {"term": item["term"], "points": item["points"], "detail": item["detail"]}
        for item in result["evidence"]
    ]
    if not evidence:
        raise ValueError("cannot explain threat without evidence")

    from mda.llm_client import generate_threat_summary_ko

    summary = generate_threat_summary_ko(result["threat"], evidence)
    with conn.cursor() as cur:
        cur.execute("UPDATE alert SET summary_ko = %s WHERE alert_id = %s", (summary, threat_id))
    return {"summary_ko": summary}


def _point_feature(lon: float, lat: float, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


def _feature_collection(features: list) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _layer_ais_points(conn, region, start: datetime, end: datetime) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (p.mmsi) ST_X(p.geom), ST_Y(p.geom), p.mmsi, "
            "p.vessel_id, v.name, p.ts, p.sog, p.cog "
            "FROM ais_position p "
            "LEFT JOIN vessel v ON v.vessel_id = p.vessel_id "
            "WHERE p.region_id = %s AND p.ts BETWEEN %s AND %s "
            "ORDER BY p.mmsi, p.ts DESC LIMIT 5000",
            (region.region_id, start, end),
        )
        rows = cur.fetchall()
    features = [
        _point_feature(
            lon,
            lat,
            {
                "mmsi": mmsi,
                "vessel_id": vessel_id,
                "name": name,
                "ts": _iso(ts),
                "sog": sog,
                "cog": cog,
            },
        )
        for lon, lat, mmsi, vessel_id, name, ts, sog, cog in rows
    ]
    return _feature_collection(features)


def _layer_tracks(conn, region, start: datetime, end: datetime, track_minutes: int = 60) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest AS (
              SELECT DISTINCT ON (mmsi) mmsi, vessel_id, ts AS latest_ts
              FROM ais_position
              WHERE region_id = %s AND ts BETWEEN %s AND %s
              ORDER BY mmsi, ts DESC
            ),
            ranked AS (
              SELECT
                p.mmsi,
                COALESCE(l.vessel_id, p.vessel_id) AS vessel_id,
                ST_X(p.geom) AS lon,
                ST_Y(p.geom) AS lat,
                p.ts,
                row_number() OVER (PARTITION BY p.mmsi ORDER BY p.ts DESC) AS rn
              FROM latest l
              JOIN ais_position p ON p.mmsi = l.mmsi
              WHERE p.region_id = %s
                AND p.ts BETWEEN %s AND l.latest_ts
            )
            SELECT mmsi, vessel_id, lon, lat, ts
            FROM ranked
            WHERE rn <= 10
            ORDER BY mmsi, ts
            """,
            (region.region_id, start, end, region.region_id, start),
        )
        rows = cur.fetchall()
    tracks: dict = {}
    for mmsi, vessel_id, lon, lat, ts in rows:
        track = tracks.setdefault(mmsi, {"vessel_id": vessel_id, "coords": []})
        if track["vessel_id"] is None and vessel_id is not None:
            track["vessel_id"] = vessel_id
        track["coords"].append([lon, lat])
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": track["coords"]},
            "properties": {
                "vessel_id": track["vessel_id"],
                "mmsi": mmsi,
                "n": len(track["coords"]),
            },
        }
        for mmsi, track in tracks.items()
        if len(track["coords"]) >= 2
    ]
    return _feature_collection(features)


def _layer_ports(conn, region, start: datetime, end: datetime) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT ST_X(geom), ST_Y(geom), name, country FROM facility WHERE kind = 'port'")
        rows = cur.fetchall()
    features = [
        _point_feature(lon, lat, {"name": name, "country": country})
        for lon, lat, name, country in rows
    ]
    return _feature_collection(features)


def _layer_cables(conn, region, start: datetime, end: datetime) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT ST_AsGeoJSON(geom), name FROM zone WHERE kind = 'cable'")
        rows = cur.fetchall()
    features = [
        {"type": "Feature", "geometry": json.loads(geom_json), "properties": {"name": name}}
        for geom_json, name in rows
    ]
    return _feature_collection(features)


def _layer_zones(conn, region, start: datetime, end: datetime) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ST_AsGeoJSON(geom), name, kind, zone_id FROM zone "
            "WHERE kind IN ('aoi', 'region', 'eez', 'gray_zone', 'territorial') "
            "OR kind LIKE 'geofence%%'"
        )
        rows = cur.fetchall()
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(geom_json),
            "properties": {"name": name, "kind": kind, "zone_id": zone_id},
        }
        for geom_json, name, kind, zone_id in rows
    ]
    return _feature_collection(features)


def _layer_events(conn, region, start: datetime, end: datetime) -> dict:
    min_lon, min_lat, max_lon, max_lat = _bbox_params(region)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ST_X(geom), ST_Y(geom), name, event_type, event_date, description "
            "FROM event WHERE geom IS NOT NULL AND event_type NOT LIKE 'gfw%%' "
            "AND (region_id = %s OR "
            "ST_Within(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))) "
            "AND event_date BETWEEN %s AND %s",
            (region.region_id, min_lon, min_lat, max_lon, max_lat, start.date(), end.date()),
        )
        rows = cur.fetchall()
    features = [
        _point_feature(
            lon,
            lat,
            {
                "name": name,
                "event_type": event_type,
                "event_date": _iso(event_date),
                "description": description,
            },
        )
        for lon, lat, name, event_type, event_date, description in rows
    ]
    return _feature_collection(features)


def _layer_gfw_events(conn, region, start: datetime, end: datetime) -> dict:
    min_lon, min_lat, max_lon, max_lat = _bbox_params(region)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ST_X(geom), ST_Y(geom), name, event_type, event_date "
            "FROM event WHERE geom IS NOT NULL AND event_type LIKE 'gfw%%' "
            "AND (region_id = %s OR "
            "ST_Within(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))) "
            "AND event_date BETWEEN %s AND %s "
            "ORDER BY event_date DESC LIMIT 10000",
            (region.region_id, min_lon, min_lat, max_lon, max_lat, start.date(), end.date()),
        )
        rows = cur.fetchall()
    features = [
        _point_feature(
            lon,
            lat,
            {
                "name": name,
                "event_type": event_type,
                "event_date": _iso(event_date),
            },
        )
        for lon, lat, name, event_type, event_date in rows
    ]
    return _feature_collection(features)


def _layer_alerts_geo(conn, region, start: datetime, end: datetime) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT alert_id, alert_type, level, score, title_ko, vessel_id "
            "FROM alert WHERE region_id = %s OR region_id IS NULL",
            (region.region_id,),
        )
        rows = cur.fetchall()
    features = []
    for alert_id, alert_type, level, score, title_ko, vessel_id in rows:
        if vessel_id is None:
            continue
        lon, lat = _last_position(conn, vessel_id, start, end)
        if lon is None or lat is None:
            continue
        features.append(
            _point_feature(
                lon,
                lat,
                {
                    "alert_id": alert_id,
                    "alert_type": alert_type,
                    "level": level,
                    "score": score,
                    "title_ko": title_ko,
                },
            )
        )
    return _feature_collection(features)


LAYERS = {
    "ais_points": _layer_ais_points,
    "tracks": _layer_tracks,
    "ports": _layer_ports,
    "cables": _layer_cables,
    "zones": _layer_zones,
    "events": _layer_events,
    "gfw_events": _layer_gfw_events,
    "alerts_geo": _layer_alerts_geo,
}


def _timeline_counts(
    conn,
    table: str,
    ts_column: str,
    trunc_unit: str,
    start: datetime,
    end: datetime,
    region_id: str,
    match_null: bool,
) -> dict:
    region_clause = "(region_id = %s OR region_id IS NULL)" if match_null else "region_id = %s"
    query = (
        f"SELECT date_trunc(%s, {ts_column}) AS bucket, count(*) FROM {table} "
        f"WHERE {ts_column} BETWEEN %s AND %s AND {region_clause} GROUP BY bucket"
    )
    with conn.cursor() as cur:
        cur.execute(query, (trunc_unit, start, end, region_id))
        rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}


def _timeline_counts_any(
    conn,
    table: str,
    ts_columns: tuple,
    trunc_unit: str,
    start: datetime,
    end: datetime,
    region_id: str,
    match_null: bool,
) -> dict:
    for ts_column in ts_columns:
        try:
            return _timeline_counts(
                conn, table, ts_column, trunc_unit, start, end, region_id, match_null
            )
        except errors.UndefinedColumn:
            conn.rollback()
            continue
    return {}


def get_timeline(conn, region, start: datetime, end: datetime, bucket: str) -> dict:
    trunc_unit = "day" if bucket == "day" else "hour"
    ais_counts = _timeline_counts(
        conn, "ais_position", "ts", trunc_unit, start, end, region.region_id, match_null=False
    )
    osint_counts = _timeline_counts_any(
        conn,
        "osint_item",
        ("published_at", "fetched_at", "ts", "created_at"),
        trunc_unit,
        start,
        end,
        region.region_id,
        match_null=True,
    )
    alert_counts = _timeline_counts(
        conn, "alert", "generated_at", trunc_unit, start, end, region.region_id, match_null=True
    )
    buckets_map: dict = {}
    for source_counts, key in (
        (ais_counts, "ais"),
        (osint_counts, "osint"),
        (alert_counts, "alerts"),
    ):
        for t, n in source_counts.items():
            entry = buckets_map.setdefault(t, {"t": t, "ais": 0, "osint": 0, "alerts": 0})
            entry[key] = n
    ordered = sorted(buckets_map.values(), key=lambda b: b["t"])
    return {
        "buckets": [
            {"t": _iso(b["t"]), "ais": b["ais"], "osint": b["osint"], "alerts": b["alerts"]}
            for b in ordered
        ]
    }


def get_osint(conn, region, start: datetime, end: datetime) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_id, ts, kind, lang, text, source_module, sentiment, weight "
            "FROM osint_item WHERE (region_id = %s OR region_id IS NULL) "
            "AND ts BETWEEN %s AND %s ORDER BY ts DESC LIMIT 500",
            (region.region_id, start, end),
        )
        rows = cur.fetchall()
    return {
        "items": [
            {
                "id": item_id,
                "ts": _iso(ts),
                "kind": kind,
                "lang": lang,
                "text": text,
                "source": source_module,
                "sentiment": sentiment,
                "weight": weight,
            }
            for item_id, ts, kind, lang, text, source_module, sentiment, weight in rows
        ]
    }


def get_ontology_tables(conn) -> list:
    tables = []
    for table in ONTOLOGY_WHITELIST:
        query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                count = cur.fetchone()[0]
        except errors.UndefinedTable:
            conn.rollback()
            count = 0
        tables.append({"table": table, "count": count})
    return tables


def _serialize_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def get_table_columns(conn, table: str) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_name = %s AND table_schema = current_schema() "
            "ORDER BY ordinal_position",
            (table,),
        )
        return cur.fetchall()


def get_table_page(conn, table: str, limit: int, offset: int) -> dict:
    limit = min(limit, 200)
    columns = get_table_columns(conn, table)
    column_names = [c[0] for c in columns]
    select_parts = []
    for name, udt_name in columns:
        if udt_name == "geometry":
            select_parts.append(
                sql.SQL("ST_AsGeoJSON({}) AS {}").format(
                    sql.Identifier(name), sql.Identifier(name)
                )
            )
        else:
            select_parts.append(sql.Identifier(name))
    order_column = next((c for c in ORDER_PRIORITY if c in column_names), column_names[0])
    query = sql.SQL("SELECT {} FROM {} ORDER BY {} DESC LIMIT %s OFFSET %s").format(
        sql.SQL(", ").join(select_parts),
        sql.Identifier(table),
        sql.Identifier(order_column),
    )
    with conn.cursor() as cur:
        cur.execute(query, (limit, offset))
        rows = cur.fetchall()
    count_query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(count_query)
        total = cur.fetchone()[0]
    serialized_rows = [[_serialize_value(v) for v in row] for row in rows]
    return {"columns": column_names, "rows": serialized_rows, "total": total}
