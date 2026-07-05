from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException

from mda.sim import registry
from mda.store import pg

LIVE_ID = "live"
LIVE_ENTRY = {
    "id": LIVE_ID,
    "name_ko": "실데이터 (LIVE)",
    "name_en": "Live data",
    "kind": "live",
    "description": None,
    "created_at": None,
}


def is_live(dataset: str | None) -> bool:
    return dataset in (None, "", LIVE_ID)


@contextmanager
def dataset_conn(dataset: str | None):
    if is_live(dataset):
        with pg.connect(readonly=True) as conn:
            yield conn
        return
    with pg.connect(readonly=True) as check:
        if not registry.scenario_exists(check, dataset):
            raise HTTPException(status_code=404, detail="unknown dataset")
    with pg.connect(readonly=True, dataset=dataset) as conn:
        yield conn


def list_datasets(conn) -> dict:
    return {
        "datasets": [LIVE_ENTRY, *registry.list_scenarios(conn)],
        "default": LIVE_ID,
    }
