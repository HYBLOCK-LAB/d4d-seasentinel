from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math

import pandas as pd
import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback, table_columns
from mda.pipelines.index import robust_z


@dataclass
class _RobustZConfig:
    baseline_days: int
    embargo_days: int
    mad_floor: float
    z_clip_min: float
    z_clip_max: float


def _axis_cfg(params: dict, axis: str) -> dict:
    return params.get("axes", {}).get(axis, {})


def _points_for_axis(params: dict, axis: str, z_value: float) -> float:
    cfg = _axis_cfg(params, axis)
    return min(cfg.get("max_points", 20.0), z_value * cfg.get("points_per_z", 4.0))


def _window_days(start: datetime, end: datetime) -> int:
    return max(1, (end.date() - start.date()).days + 1)


def _history_start(start: datetime, end: datetime, params: dict) -> date:
    days = (
        int(params.get("baseline_days", 30))
        + int(params.get("embargo_days", 1))
        + _window_days(start, end)
        + 7
    )
    return start.date() - timedelta(days=days)


def _z_config(params: dict) -> _RobustZConfig:
    return _RobustZConfig(
        baseline_days=int(params.get("baseline_days", 30)),
        embargo_days=int(params.get("embargo_days", 1)),
        mad_floor=float(params.get("mad_floor", 0.5)),
        z_clip_min=float(params.get("z_clip_min", 0.0)),
        z_clip_max=float(params.get("z_clip_max", 6.0)),
    )


def _rolling_z_by_zone(
    rows: list[tuple[str, date, float]],
    zone_ids: list[str],
    start: datetime,
    end: datetime,
    params: dict,
) -> dict[str, tuple[float, float]]:
    history_start = _history_start(start, end, params)
    end_day = end.date()
    index = pd.date_range(history_start, end_day, freq="D")
    values_by_zone = {zone_id: pd.Series(0.0, index=index) for zone_id in zone_ids}
    for zone_id, day, value in rows:
        if zone_id in values_by_zone and day is not None:
            ts = pd.Timestamp(day)
            if ts in values_by_zone[zone_id].index:
                values_by_zone[zone_id].loc[ts] += float(value or 0.0)

    cfg = _z_config(params)
    current: dict[str, tuple[float, float]] = {}
    rolling_window = _window_days(start, end)
    for zone_id, series in values_by_zone.items():
        windowed = series.rolling(rolling_window, min_periods=1).sum()
        z_series = robust_z(windowed, cfg)
        z_value = z_series.iloc[-1]
        current_value = windowed.iloc[-1]
        if pd.isna(z_value) or current_value <= 0:
            continue
        current[zone_id] = (float(current_value), float(z_value))
    return current


def _fetch_zones(conn: psycopg.Connection, kinds: list[str]):
    with conn.cursor() as cur:
        cur.execute(
            "select zone_id, name, kind, region_id, ST_X(ST_Centroid(geom)), ST_Y(ST_Centroid(geom)) "
            "from zone where kind = any(%s)",
            (kinds,),
        )
        return cur.fetchall()


def _fetch_vessel_presence(conn: psycopg.Connection, kinds: list[str], start_day: date, end_day: date):
    with conn.cursor() as cur:
        cur.execute(
            "select z.zone_id, p.ts::date as day, count(distinct p.vessel_id)::double precision "
            "from zone z join ais_position p on ST_Intersects(z.geom, p.geom) "
            "where z.kind = any(%s) and p.vessel_id is not null and p.ts::date between %s and %s "
            "group by z.zone_id, p.ts::date",
            (kinds, start_day, end_day),
        )
        return cur.fetchall()


def _fetch_cluster_hits(conn: psycopg.Connection, kinds: list[str], start_day: date, end_day: date, params: dict):
    with conn.cursor() as cur:
        cur.execute(
            "with points as ("
            "  select z.zone_id, p.vessel_id, p.ts::date as day, p.geom "
            "  from zone z join ais_position p on ST_Intersects(z.geom, p.geom) "
            "  where z.kind = any(%s) and p.vessel_id is not null and p.ts::date between %s and %s"
            "), clustered as ("
            "  select zone_id, day, vessel_id, "
            "  ST_ClusterDBSCAN(geom, eps := %s, minpoints := %s) "
            "    over (partition by zone_id, day) as cid "
            "  from points"
            "), cluster_sizes as ("
            "  select zone_id, day, cid, count(distinct vessel_id) as n "
            "  from clustered where cid is not null "
            "  group by zone_id, day, cid having count(distinct vessel_id) >= %s"
            ") "
            "select zone_id, day, count(*)::double precision from cluster_sizes group by zone_id, day",
            (
                kinds,
                start_day,
                end_day,
                params.get("cluster_eps_degrees", 0.03),
                params.get("cluster_dbscan_minpoints", 3),
                params.get("cluster_min_size", 8),
            ),
        )
        return cur.fetchall()


def _fetch_gfw_gap_events(conn: psycopg.Connection, kinds: list[str], start_day: date, end_day: date):
    columns = table_columns(conn, "event")
    if "geom" not in columns:
        return []
    day_sql = "e.ts::date" if "ts" in columns else "e.event_date"
    with conn.cursor() as cur:
        cur.execute(
            f"select z.zone_id, {day_sql} as day, count(*)::double precision "
            "from zone z join event e on e.geom is not null and ST_Intersects(z.geom, e.geom) "
            f"where z.kind = any(%s) and e.event_type = 'gfw_gap' and {day_sql} between %s and %s "
            f"group by z.zone_id, {day_sql}",
            (kinds, start_day, end_day),
        )
        return cur.fetchall()


def _fetch_gdelt(conn: psycopg.Connection, kinds: list[str], start_day: date, end_day: date, tone: bool):
    signal_clause = "s.signal_name = 'gdelt_tone'" if tone else "s.signal_name like 'gdelt_%' and s.signal_name <> 'gdelt_tone'"
    with conn.cursor() as cur:
        cur.execute(
            "with zmap as ("
            "  select zone_id, case when zone_id like 'aoi:%%' then substring(zone_id from 5) else zone_id end as aoi_id "
            "  from zone where kind = any(%s)"
            ") "
            "select z.zone_id, s.date, sum(s.value)::double precision "
            "from zmap z join signal_daily s on s.aoi_id = z.aoi_id "
            f"where {signal_clause} and s.date between %s and %s "
            "group by z.zone_id, s.date",
            (kinds, start_day, end_day),
        )
        return cur.fetchall()


def _fetch_osint_counts(conn: psycopg.Connection, kinds: list[str], start_day: date, end_day: date):
    with conn.cursor() as cur:
        cur.execute(
            "select z.zone_id, o.ts::date as day, count(*)::double precision "
            "from zone z join osint_item o on o.region_id = z.region_id "
            "where z.kind = any(%s) and o.ts::date between %s and %s "
            "group by z.zone_id, o.ts::date",
            (kinds, start_day, end_day),
        )
        return cur.fetchall()


def _fetch_weather(conn: psycopg.Connection, kinds: list[str], start_day: date, end_day: date):
    with conn.cursor() as cur:
        cur.execute(
            "select z.zone_id, avg(w.wave_height), avg(w.wind_speed), max(w.date) "
            "from zone z join weather_daily w on w.region_id = z.region_id "
            "where z.kind = any(%s) and w.date between %s and %s "
            "group by z.zone_id",
            (kinds, start_day, end_day),
        )
        return cur.fetchall()


def _fetch_historical_prior(conn: psycopg.Connection, kinds: list[str], end_day: date):
    with conn.cursor() as cur:
        cur.execute(
            "select z.zone_id, count(*) "
            "from zone z join event e on (e.zone_id = z.zone_id or (e.geom is not null and ST_Intersects(z.geom, e.geom))) "
            "where z.kind = any(%s) and e.event_date < %s "
            "and extract(month from e.event_date) = %s "
            "and (e.source_id = 'curated_incident' or e.collector = 'reference_incidents' or e.raw_ref = 'config/incidents.yaml') "
            "group by z.zone_id",
            (kinds, end_day, end_day.month),
        )
        return cur.fetchall()


def _axis_detection(
    zone,
    term: str,
    points: float,
    detail: str,
    src_table: str,
    src_id: str,
    end: datetime,
) -> Detection:
    zone_id, name, kind, region_id, lon, lat = zone
    return Detection(
        subject_type="zone",
        subject_id=zone_id,
        term=term,
        points=points,
        src_table=src_table,
        src_id=src_id,
        detail=f"{name or zone_id}: {detail}",
        lon=lon,
        lat=lat,
        ts=end,
    )


@register("zone_anomaly", "zone")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    start, end = window
    kinds = list(params.get("zone_kinds", ["gray_zone", "aoi"]))
    try:
        zones = _fetch_zones(conn, kinds)
    except psycopg.Error:
        rollback(conn)
        return []
    if not zones:
        return []

    zone_ids = [row[0] for row in zones]
    zones_by_id = {row[0]: row for row in zones}
    start_day = _history_start(start, end, params)
    end_day = end.date()
    min_z = float(params.get("min_z", 1.5))
    detections: list[Detection] = []

    axis_fetchers = {
        "zone_vessel_presence_z": lambda: _fetch_vessel_presence(conn, kinds, start_day, end_day),
        "zone_cluster_hits_z": lambda: _fetch_cluster_hits(conn, kinds, start_day, end_day, params),
        "zone_gfw_gap_events_z": lambda: _fetch_gfw_gap_events(conn, kinds, start_day, end_day),
        "zone_gdelt_tone_z": lambda: _fetch_gdelt(conn, kinds, start_day, end_day, tone=True),
        "zone_gdelt_volume_z": lambda: _fetch_gdelt(conn, kinds, start_day, end_day, tone=False),
        "zone_osint_count_z": lambda: _fetch_osint_counts(conn, kinds, start_day, end_day),
    }
    for term, fetch in axis_fetchers.items():
        try:
            rows = fetch()
        except psycopg.Error:
            rollback(conn)
            continue
        z_values = _rolling_z_by_zone(rows, zone_ids, start, end, params)
        for zone_id, (current_value, z_value) in z_values.items():
            # Standing gauge: every finite axis contributes; z below min_z
            # yields 0 points but keeps the axis visible in evidence.
            z_eff = max(z_value, 0.0)
            axis_points = _points_for_axis(params, term, z_eff) if z_eff >= min_z else 0.0
            detections.append(
                _axis_detection(
                    zones_by_id[zone_id],
                    term,
                    axis_points,
                    f"current-window value {current_value:.1f}, robust z={z_value:.2f}"
                    + ("" if z_eff >= min_z else " (정상 범위)"),
                    "zone",
                    zone_id,
                    end,
                )
            )

    try:
        weather_rows = _fetch_weather(conn, kinds, start.date(), end.date())
    except psycopg.Error:
        rollback(conn)
        weather_rows = []
    for zone_id, wave_height, wind_speed, weather_day in weather_rows:
        if wave_height is None or wind_speed is None:
            continue
        if (
            wave_height <= params.get("weather_wave_max_m", 1.2)
            and params.get("weather_wind_min_ms", 2.0) <= wind_speed <= params.get("weather_wind_max_ms", 10.0)
        ):
            detections.append(
                _axis_detection(
                    zones_by_id[zone_id],
                    "zone_weather_favorable",
                    params.get("weather_points", 4.0),
                    f"low wave {wave_height:.1f}m and moderate wind {wind_speed:.1f}m/s",
                    "weather_daily",
                    f"{zone_id}:{weather_day.isoformat() if weather_day else end.date().isoformat()}",
                    end,
                )
            )

    try:
        prior_rows = _fetch_historical_prior(conn, kinds, end.date())
    except psycopg.Error:
        rollback(conn)
        prior_rows = []
    for zone_id, count in prior_rows:
        points = min(params.get("historical_prior_max_points", 12.0), count * params.get("historical_prior_points_each", 3.0))
        if points <= 0:
            continue
        detections.append(
            _axis_detection(
                zones_by_id[zone_id],
                "zone_historical_prior",
                points,
                f"{count} curated incidents in this calendar month across prior years",
                "event",
                zone_id,
                end,
            )
        )

    covered = {d.subject_id for d in detections}
    for zone_id, zone_row in zones_by_id.items():
        if zone_id not in covered:
            detections.append(
                _axis_detection(
                    zone_row,
                    "zone_baseline",
                    0.0,
                    "관측 축 이상 없음 — 정상 범위",
                    "zone",
                    zone_id,
                    end,
                )
            )
    return [d for d in detections if math.isfinite(d.points)]
