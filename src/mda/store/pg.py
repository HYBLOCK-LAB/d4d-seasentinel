from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv
from psycopg import sql

from mda.paths import repo_root, schema_sql

_env_loaded = False


def dsn() -> str:
    global _env_loaded
    if not _env_loaded:
        load_dotenv(repo_root() / ".env")
        _env_loaded = True
    value = os.environ.get("MDA_PG_DSN")
    if not value:
        raise RuntimeError("MDA_PG_DSN not set")
    return value


_SCHEMA_RE = __import__("re").compile(r"^[a-z][a-z0-9_]{0,40}$")


def scenario_schema(dataset: str) -> str:
    if not _SCHEMA_RE.match(dataset):
        raise ValueError(f"invalid dataset id: {dataset!r}")
    return f"sim_{dataset}"


@contextmanager
def connect(readonly: bool = False, dataset: str | None = None):
    # search_path is set as a libpq startup option (not a post-connect SET) so it
    # survives transaction rollbacks; a plain SET would revert to public on rollback.
    options = f"-c search_path={scenario_schema(dataset)},public" if dataset else None
    conn = psycopg.connect(dsn(), autocommit=False, options=options)
    try:
        if readonly:
            conn.read_only = True
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(conn: psycopg.Connection) -> None:
    conn.execute(schema_sql().read_text())


def upsert(
    conn: psycopg.Connection,
    table: str,
    rows: list[dict],
    conflict: list[str],
    update: list[str] | None = None,
) -> int:
    if not rows:
        return 0
    columns = list(rows[0].keys())
    col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    placeholders = sql.SQL(", ").join(sql.Placeholder(c) for c in columns)
    conflict_sql = sql.SQL(", ").join(sql.Identifier(c) for c in conflict)
    if update:
        set_sql = sql.SQL(", ").join(
            sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in update
        )
        action = sql.SQL("DO UPDATE SET {set_sql}").format(set_sql=set_sql)
    else:
        action = sql.SQL("DO NOTHING")
    statement = sql.SQL(
        "INSERT INTO {table} ({cols}) VALUES ({vals}) ON CONFLICT ({conflict}) {action}"
    ).format(
        table=sql.Identifier(table),
        cols=col_sql,
        vals=placeholders,
        conflict=conflict_sql,
        action=action,
    )
    with conn.cursor() as cur:
        cur.executemany(statement, rows)
    return len(rows)


def count(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        return cur.fetchone()[0]
