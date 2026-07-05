from __future__ import annotations

from datetime import datetime

from psycopg import sql

from mda.store import pg

REFERENCE_TABLES = [
    "source",
    "method_registry",
    "vessel",
    "facility",
    "zone",
    "document",
    "entity_link",
]

WINDOW_TABLES = {
    "ais_position": ("ts", "region_id"),
    "osint_item": ("ts", "region_id"),
    "sar_detection": ("ts", "region_id"),
    "alert": ("generated_at", "region_id"),
    "event": ("event_date", "region_id"),
    "weather_daily": ("date", "region_id"),
    "signal_daily": ("date", None),
    "index_daily": ("date", None),
    "index_contribution": ("date", None),
}

ALERT_CHILD_TABLES = ["alert_evidence", "alert_timeline_step"]


def capture(
    conn,
    scenario_id: str,
    start: datetime,
    end: datetime,
    region_id: str | None = None,
) -> dict:
    schema = sql.Identifier(pg.scenario_schema(scenario_id))
    conn.execute("SET search_path TO public")
    copied: dict[str, int] = {}
    for table in REFERENCE_TABLES:
        ident = sql.Identifier(table)
        cur = conn.execute(
            sql.SQL(
                "INSERT INTO {s}.{t} SELECT * FROM public.{t} ON CONFLICT DO NOTHING"
            ).format(s=schema, t=ident)
        )
        copied[table] = cur.rowcount
    for table, (ts_column, region_column) in WINDOW_TABLES.items():
        clauses = [sql.SQL("{c} BETWEEN %s AND %s").format(c=sql.Identifier(ts_column))]
        params: list = [start, end]
        if region_id and region_column:
            clauses.append(
                sql.SQL("({c} = %s OR {c} IS NULL)").format(c=sql.Identifier(region_column))
            )
            params.append(region_id)
        cur = conn.execute(
            sql.SQL(
                "INSERT INTO {s}.{t} SELECT * FROM public.{t} WHERE {w} "
                "ON CONFLICT DO NOTHING"
            ).format(s=schema, t=sql.Identifier(table), w=sql.SQL(" AND ").join(clauses)),
            params,
        )
        copied[table] = cur.rowcount
    for table in ALERT_CHILD_TABLES:
        cur = conn.execute(
            sql.SQL(
                "INSERT INTO {s}.{t} SELECT c.* FROM public.{t} c "
                "JOIN {s}.alert a ON a.alert_id = c.alert_id ON CONFLICT DO NOTHING"
            ).format(s=schema, t=sql.Identifier(table))
        )
        copied[table] = cur.rowcount
    return copied
