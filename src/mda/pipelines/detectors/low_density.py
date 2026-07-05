from __future__ import annotations

from statistics import median

import psycopg

from mda.pipelines.detectors.core import Detection, Window, register, rollback


def span_bucket(span_hours: float) -> str:
    if span_hours < 6:
        return "short"
    if span_hours < 24:
        return "day"
    return "multi_day"


@register("low_density", "vessel")
def detect(conn: psycopg.Connection, window: Window, params: dict) -> list[Detection]:
    start, end = window
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select vessel_id, region_id, count(*), min(ts), max(ts), "
                "ST_X(ST_Centroid(ST_Collect(geom))), ST_Y(ST_Centroid(ST_Collect(geom))) "
                "from ais_position "
                "where vessel_id is not null and ts between %s and %s "
                "group by vessel_id, region_id",
                (start, end),
            )
            rows = cur.fetchall()
    except psycopg.Error:
        rollback(conn)
        return []

    enriched = []
    counts_by_peer: dict[tuple[str | None, str], list[int]] = {}
    for vessel_id, region_id, count, min_ts, max_ts, lon, lat in rows:
        span_h = max((max_ts - min_ts).total_seconds() / 3600.0, 0.0)
        if span_h < params["min_span_hours"]:
            continue
        bucket = span_bucket(span_h)
        enriched.append((vessel_id, region_id, count, min_ts, max_ts, lon, lat, span_h, bucket))
        counts_by_peer.setdefault((region_id, bucket), []).append(count)

    detections: list[Detection] = []
    for vessel_id, region_id, count, min_ts, max_ts, lon, lat, span_h, bucket in enriched:
        peer_counts = counts_by_peer[(region_id, bucket)]
        if len(peer_counts) < params["min_peers"]:
            continue
        peer_median = float(median(peer_counts))
        if peer_median <= 0 or count >= peer_median * params["ratio"]:
            continue
        detections.append(
            Detection(
                subject_type="vessel",
                subject_id=vessel_id,
                term="low_density",
                points=params["points"],
                src_table="ais_position",
                src_id=f"{vessel_id}:low_density:{min_ts.isoformat()}",
                detail=(
                    f"{count} fixes over {span_h:.1f}h; peer median {peer_median:.1f} "
                    f"for {region_id or 'unknown'} {bucket} presence"
                ),
                lon=lon,
                lat=lat,
                ts=max_ts,
            )
        )
    return detections
