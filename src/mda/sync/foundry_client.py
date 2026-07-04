from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

from mda.paths import repo_root

_env_loaded = False


def _env() -> tuple[str | None, str | None]:
    global _env_loaded
    if not _env_loaded:
        load_dotenv(repo_root() / ".env")
        _env_loaded = True
    return os.environ.get("FOUNDRY_HOST") or None, os.environ.get("FOUNDRY_TOKEN") or None


class FoundryClient:
    def __init__(self):
        self.host, self.token = _env()

    def configured(self) -> bool:
        return bool(self.host and self.token)

    def upsert(self, object_type: str, primary_key: str, objects: list[dict]) -> dict:
        if not self.configured():
            return {"object_type": object_type, "planned": len(objects), "mode": "dry_run"}
        url = f"{self.host}/api/v2/ontologies/objects/{object_type}/upsert"
        sent = 0
        with httpx.Client(timeout=120.0, headers={"Authorization": f"Bearer {self.token}"}) as client:
            for batch_start in range(0, len(objects), 200):
                batch = objects[batch_start : batch_start + 200]
                resp = client.post(url, json={"primaryKey": primary_key, "objects": batch})
                resp.raise_for_status()
                sent += len(batch)
        return {"object_type": object_type, "sent": sent, "mode": "live"}
