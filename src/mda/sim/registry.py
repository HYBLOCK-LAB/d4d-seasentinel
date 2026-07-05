from __future__ import annotations

import re

from psycopg import sql

from mda.store import pg

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def validate_id(scenario_id: str) -> str:
    if not ID_RE.match(scenario_id):
        raise ValueError(f"invalid scenario id: {scenario_id!r}")
    return scenario_id


def create_scenario(
    conn,
    scenario_id: str,
    name_ko: str,
    name_en: str | None = None,
    description: str | None = None,
    kind: str = "assumed",
) -> None:
    validate_id(scenario_id)
    schema = pg.scenario_schema(scenario_id)
    conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
    conn.execute(
        sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
    )
    pg.ensure_schema(conn)
    conn.execute("SET search_path TO public")
    pg.upsert(
        conn,
        "scenario",
        [
            {
                "scenario_id": scenario_id,
                "name_ko": name_ko,
                "name_en": name_en,
                "description": description,
                "kind": kind,
            }
        ],
        conflict=["scenario_id"],
        update=["name_ko", "name_en", "description", "kind"],
    )


def drop_scenario(conn, scenario_id: str) -> None:
    validate_id(scenario_id)
    conn.execute(
        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
            sql.Identifier(pg.scenario_schema(scenario_id))
        )
    )
    conn.execute("DELETE FROM public.scenario WHERE scenario_id = %s", (scenario_id,))


def list_scenarios(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT scenario_id, name_ko, name_en, description, kind, created_at "
            "FROM public.scenario ORDER BY created_at"
        )
        rows = cur.fetchall()
    return [
        {
            "id": scenario_id,
            "name_ko": name_ko,
            "name_en": name_en,
            "description": description,
            "kind": kind,
            "created_at": created_at.isoformat(),
        }
        for scenario_id, name_ko, name_en, description, kind, created_at in rows
    ]


def scenario_exists(conn, scenario_id: str) -> bool:
    if not ID_RE.match(scenario_id):
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM public.scenario WHERE scenario_id = %s", (scenario_id,))
        return cur.fetchone() is not None
