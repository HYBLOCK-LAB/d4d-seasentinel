from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from psycopg.rows import dict_row

from mda.store import lake, pg, s3

LOG = logging.getLogger(__name__)
DEFAULT_KEEP_DAYS = 14
DEFAULT_BATCH_SIZE = 50_000


def _utc_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def bucket_10min(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % 600), tz=timezone.utc)


def _archive_path(day: date) -> Path:
    return lake.lake_dir("ais_archive", f"date={day.isoformat()}") / "snapshot.parquet"


def _affected_days(conn, cutoff: datetime, max_days: int | None = None) -> list[date]:
    sql = """
        select (ts at time zone 'UTC')::date as day
        from ais_position
        where ts < %s
        group by 1
        order by 1
    """
    params: list[Any] = [cutoff]
    if max_days is not None:
        sql += " limit %s"
        params.append(max_days)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [row[0] for row in cur.fetchall()]


def _day_row_count(conn, day: date, cutoff: datetime) -> int:
    start, stop = _utc_day_bounds(day)
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from ais_position where ts >= %s and ts < %s and ts < %s",
            (start, stop, cutoff),
        )
        return int(cur.fetchone()[0])


def _write_snapshot(conn, day: date, cutoff: datetime, batch_size: int) -> tuple[Path, int, bool]:
    path = _archive_path(day)
    if path.exists():
        return path, _day_row_count(conn, day, cutoff), False

    start, stop = _utc_day_bounds(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    written = 0
    writer: pq.ParquetWriter | None = None
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select
                    mmsi,
                    ts,
                    vessel_id,
                    ST_AsEWKT(geom) as geom,
                    sog,
                    cog,
                    heading,
                    nav_status,
                    msg_type,
                    region_id,
                    source_id,
                    collector,
                    fetched_at,
                    raw_ref
                from ais_position
                where ts >= %s and ts < %s and ts < %s
                order by mmsi, ts
                """,
                (start, stop, cutoff),
            )
            while True:
                batch = cur.fetchmany(batch_size)
                if not batch:
                    break
                table = pa.Table.from_pylist(batch)
                if writer is None:
                    writer = pq.ParquetWriter(tmp, table.schema)
                writer.write_table(table)
                written += len(batch)
        if writer is not None:
            writer.close()
            os.replace(tmp, path)
        else:
            tmp.unlink(missing_ok=True)
        return path, written, True
    except BaseException:
        if writer is not None:
            writer.close()
        tmp.unlink(missing_ok=True)
        raise


def _upload_snapshot(path: Path) -> bool:
    key = f"lake/ais_archive/{path.parent.name}/{path.name}"
    try:
        s3.upload_file(str(path), key)
        return True
    except Exception as exc:
        LOG.info("ais retention S3 upload skipped path=%s reason=%s", path, exc)
        return False


def _thin_batch(conn, cutoff: datetime, batch_size: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            with ranked as (
                select
                    ctid,
                    row_number() over (
                        partition by mmsi, floor(extract(epoch from ts) / 600)
                        order by ts asc, fetched_at asc
                    ) as rn
                from ais_position
                where ts < %s
            ),
            doomed as (
                select ctid
                from ranked
                where rn > 1
                limit %s
            )
            delete from ais_position a
            using doomed
            where a.ctid = doomed.ctid
            """,
            (cutoff, batch_size),
        )
        return cur.rowcount or 0


def thin_ais_positions(conn, cutoff: datetime, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    deleted = 0
    while True:
        count = _thin_batch(conn, cutoff, batch_size)
        deleted += count
        if count < batch_size:
            return deleted


def run_retention(
    keep_days: int = DEFAULT_KEEP_DAYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)

    archived_rows = 0
    snapshots_written = 0
    s3_uploaded = 0
    with pg.connect() as conn:
        days = _affected_days(conn, cutoff, max_days=max_days)
        for day in days:
            path, rows, wrote = _write_snapshot(conn, day, cutoff, batch_size)
            archived_rows += rows
            snapshots_written += int(wrote)
            if path.exists():
                s3_uploaded += int(_upload_snapshot(path))
        deleted = thin_ais_positions(conn, cutoff, batch_size=batch_size)
    return {
        "affected_days": len(days),
        "archived_rows": archived_rows,
        "snapshots_written": snapshots_written,
        "s3_uploaded": s3_uploaded,
        "deleted_rows": deleted,
    }
