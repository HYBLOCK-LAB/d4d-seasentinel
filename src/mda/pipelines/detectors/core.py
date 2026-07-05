from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import psycopg


Window = tuple[datetime, datetime]


@dataclass(frozen=True)
class Detection:
    subject_type: str
    subject_id: str
    term: str
    points: float
    detail: str
    src_table: str
    src_id: str
    lon: float | None = None
    lat: float | None = None
    ts: datetime | None = None


DetectFunc = Callable[[psycopg.Connection, Window, dict], list[Detection]]


@dataclass(frozen=True)
class DetectorRegistration:
    name: str
    subject: str
    func: DetectFunc


REGISTRY: dict[str, DetectorRegistration] = {}


def register(name: str, subject: str) -> Callable[[DetectFunc], DetectFunc]:
    if subject not in {"vessel", "zone"}:
        raise ValueError(f"unsupported detector subject: {subject}")

    def decorator(func: DetectFunc) -> DetectFunc:
        REGISTRY[name] = DetectorRegistration(name=name, subject=subject, func=func)
        return func

    return decorator


def effective_gap_hours(
    gap_start: datetime, gap_end: datetime, outages: list[tuple[datetime, datetime | None]]
) -> float:
    raw = (gap_end - gap_start).total_seconds() / 3600.0
    overlap_total = 0.0
    for started_at, ended_at in outages:
        outage_end = ended_at if ended_at is not None else gap_end
        overlap_start = max(gap_start, started_at)
        overlap_end = min(gap_end, outage_end)
        if overlap_end > overlap_start:
            overlap_total += (overlap_end - overlap_start).total_seconds() / 3600.0
    return max(0.0, raw - overlap_total)


def rollback(conn: psycopg.Connection) -> None:
    try:
        conn.rollback()
    except psycopg.Error:
        pass


def table_columns(conn: psycopg.Connection, table: str) -> set[str]:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select column_name from information_schema.columns "
                "where table_schema = current_schema() and table_name = %s",
                (table,),
            )
            return {row[0] for row in cur.fetchall()}
    except psycopg.Error:
        rollback(conn)
        return set()


def has_columns(conn: psycopg.Connection, table: str, columns: set[str]) -> bool:
    return columns.issubset(table_columns(conn, table))
