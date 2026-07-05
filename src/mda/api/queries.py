import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg
from psycopg import errors, sql

from mda.config import load_aois, load_regions

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
    return counts


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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT alert_id, alert_type, level, score, title_ko, title_en, "
            "region_id, vessel_id, generated_at FROM alert "
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
            }
        )
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
            }
        )
    return threats


def get_threats(conn, region, start: datetime, end: datetime) -> list:
    threats = _get_vessel_threats(conn, region, start, end) + _get_area_threats(
        conn, region, start, end
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT alert_id, alert_type, level, score, title_ko, title_en, "
            "region_id, vessel_id, generated_at FROM alert WHERE alert_id = %s",
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
        generated_at,
    ) = row
    lon, lat = (None, None)
    if vessel_id is not None:
        lon, lat = _last_position(conn, vessel_id, None, None)
    threat = {
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
    }
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
    }
    return {"threat": threat, "evidence": _get_area_evidence(conn, aoi_id, threat_date)}


def get_threat_evidence(conn, threat_id: str):
    if threat_id.startswith("area:"):
        return _get_area_threat_evidence(conn, threat_id)
    return _get_vessel_threat_evidence(conn, threat_id)


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
            "SELECT ST_X(geom), ST_Y(geom), mmsi, vessel_id, ts, sog, cog "
            "FROM ais_position WHERE region_id = %s AND ts BETWEEN %s AND %s "
            "ORDER BY ts LIMIT 20000",
            (region.region_id, start, end),
        )
        rows = cur.fetchall()
    features = [
        _point_feature(
            lon,
            lat,
            {"mmsi": mmsi, "vessel_id": vessel_id, "ts": _iso(ts), "sog": sog, "cog": cog},
        )
        for lon, lat, mmsi, vessel_id, ts, sog, cog in rows
    ]
    return _feature_collection(features)


TRACK_SPLIT_GAP = timedelta(hours=1)


def _layer_tracks(conn, region, start: datetime, end: datetime) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT vessel_id, ST_X(geom), ST_Y(geom), ts FROM ais_position "
            "WHERE region_id = %s AND ts BETWEEN %s AND %s ORDER BY vessel_id, ts",
            (region.region_id, start, end),
        )
        rows = cur.fetchall()
    segments: list = []
    prev_vessel = None
    prev_ts = None
    current: list = []
    for vessel_id, lon, lat, ts in rows:
        if vessel_id != prev_vessel or (prev_ts is not None and ts - prev_ts > TRACK_SPLIT_GAP):
            if len(current) >= 2:
                segments.append((prev_vessel, current))
            current = []
        current.append([lon, lat])
        prev_vessel, prev_ts = vessel_id, ts
    if len(current) >= 2:
        segments.append((prev_vessel, current))
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"vessel_id": vessel_id, "n": len(coords)},
        }
        for vessel_id, coords in segments
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
            "SELECT ST_AsGeoJSON(geom), name, kind FROM zone "
            "WHERE kind IN ('aoi', 'region') OR kind LIKE 'geofence%%'"
        )
        rows = cur.fetchall()
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(geom_json),
            "properties": {"name": name, "kind": kind},
        }
        for geom_json, name, kind in rows
    ]
    return _feature_collection(features)


def _layer_events(conn, region, start: datetime, end: datetime) -> dict:
    min_lon, min_lat, max_lon, max_lat = _bbox_params(region)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ST_X(geom), ST_Y(geom), name, event_type, event_date, description "
            "FROM event WHERE geom IS NOT NULL AND (region_id = %s OR "
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
