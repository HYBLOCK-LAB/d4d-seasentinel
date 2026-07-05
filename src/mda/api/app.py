from contextlib import contextmanager
from datetime import datetime
from threading import Lock

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from mda.api import llm, queries
from mda.paths import repo_root
from mda.store import pg

app = FastAPI(title="SeaSentinel MDA API")
app.include_router(llm.router, prefix="/api")

_changes_conn: psycopg.Connection | None = None
_changes_conn_lock = Lock()


@contextmanager
def _changes_connection():
    global _changes_conn
    with _changes_conn_lock:
        try:
            if _changes_conn is None or _changes_conn.closed:
                _changes_conn = psycopg.connect(pg.dsn(), autocommit=False)
                _changes_conn.read_only = True
            yield _changes_conn
            _changes_conn.commit()
        except Exception:
            if _changes_conn is not None and not _changes_conn.closed:
                _changes_conn.rollback()
                _changes_conn.close()
            _changes_conn = None
            raise


@app.on_event("shutdown")
def close_changes_connection() -> None:
    global _changes_conn
    with _changes_conn_lock:
        if _changes_conn is not None and not _changes_conn.closed:
            _changes_conn.close()
        _changes_conn = None


@app.get("/api/health")
def health() -> dict:
    db_ok = False
    try:
        with pg.connect(readonly=True) as conn:
            db_ok = queries.check_db(conn)
    except Exception:
        db_ok = False
    ok = bool(llm.LLM_API_KEY)
    return {"ok": ok, "model": llm.LLM_MODEL or None, "db": db_ok}


@app.get("/api/meta")
def meta() -> dict:
    with pg.connect(readonly=True) as conn:
        return queries.get_meta(conn)


@app.get("/api/changes")
def changes(region: str = Query(...)) -> dict:
    with _changes_connection() as conn:
        resolved_region = queries.resolve_region(region)
        return queries.get_changes(conn, resolved_region)


@app.get("/api/threats")
def threats(
    region: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    with pg.connect(readonly=True) as conn:
        resolved_region = queries.resolve_region(region)
        if start is None or end is None:
            default_start, default_end = queries.compute_window(conn)
            start = start or default_start
            end = end or default_end
        return {"threats": queries.get_threats(conn, resolved_region, start, end)}


@app.get("/api/threats/{threat_id}/evidence")
def threat_evidence(threat_id: str) -> dict:
    with pg.connect(readonly=True) as conn:
        result = queries.get_threat_evidence(conn, threat_id)
    if result is None:
        raise HTTPException(status_code=404, detail="threat not found")
    return result


@app.post("/api/threats/{threat_id}/explain")
def threat_explain(threat_id: str) -> dict:
    try:
        with pg.connect() as conn:
            result = queries.explain_threat(conn, threat_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="threat not found")
    return result


@app.get("/api/layers/{layer_id}")
def layer(
    layer_id: str,
    region: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    track_minutes: int = Query(60, ge=1),
) -> dict:
    handler = queries.LAYERS.get(layer_id)
    if handler is None:
        raise HTTPException(status_code=404, detail="unknown layer")
    with pg.connect(readonly=True) as conn:
        resolved_region = queries.resolve_region(region)
        if start is None or end is None:
            default_start, default_end = queries.compute_window(conn)
            start = start or default_start
            end = end or default_end
        if layer_id == "tracks":
            return handler(conn, resolved_region, start, end, track_minutes)
        return handler(conn, resolved_region, start, end)


@app.get("/api/timeline")
def timeline(
    region: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    bucket: str = "hour",
) -> dict:
    with pg.connect(readonly=True) as conn:
        resolved_region = queries.resolve_region(region)
        if start is None or end is None:
            default_start, default_end = queries.compute_window(conn)
            start = start or default_start
            end = end or default_end
        return queries.get_timeline(conn, resolved_region, start, end, bucket)


@app.get("/api/osint")
def osint(
    region: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    with pg.connect(readonly=True) as conn:
        resolved_region = queries.resolve_region(region)
        if start is None or end is None:
            default_start, default_end = queries.compute_window(conn)
            start = start or default_start
            end = end or default_end
        return queries.get_osint(conn, resolved_region, start, end)


@app.get("/api/ontology/tables")
def ontology_tables() -> list:
    with pg.connect(readonly=True) as conn:
        return queries.get_ontology_tables(conn)


@app.get("/api/ontology/{table}")
def ontology_table(
    table: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    if table not in queries.ONTOLOGY_WHITELIST:
        raise HTTPException(status_code=404, detail="unknown table")
    with pg.connect(readonly=True) as conn:
        return queries.get_table_page(conn, table, limit, offset)


_dist_dir = repo_root() / "web" / "dist"
if _dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(_dist_dir), html=True), name="static")
