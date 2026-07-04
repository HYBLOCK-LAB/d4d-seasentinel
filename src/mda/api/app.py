from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from mda.api import llm, queries
from mda.paths import repo_root
from mda.store import pg

app = FastAPI(title="SeaSentinel MDA API")
app.include_router(llm.router, prefix="/api")


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


@app.get("/api/layers/{layer_id}")
def layer(
    layer_id: str,
    region: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
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
