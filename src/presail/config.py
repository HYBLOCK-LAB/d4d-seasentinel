from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import yaml

from presail.paths import repo_root


@dataclass
class Aoi:
    aoi_id: str
    name: str
    role: str
    bbox: list[float]
    coords_verified: bool


@dataclass
class Event:
    event_id: str
    name: str
    event_date: date
    aoi_id: str
    search_days_before: int
    search_days_after: int


@dataclass
class Thresholds:
    watch: float
    alert: float


@dataclass
class IndexConfig:
    baseline_days: int
    embargo_days: int
    mad_floor: float
    z_clip_min: float
    z_clip_max: float
    transform_k: float
    ffill_max_days: int
    thresholds: Thresholds
    weights: dict[str, float]


def _load_yaml(relative_path: str):
    path = repo_root() / relative_path
    with path.open() as f:
        return yaml.safe_load(f)


def load_aois() -> list[Aoi]:
    return [Aoi(**item) for item in _load_yaml("config/aois.yaml")]


def load_events() -> list[Event]:
    return [Event(**item) for item in _load_yaml("config/events.yaml")]


def load_index_config() -> IndexConfig:
    data = _load_yaml("config/index.yaml")
    data["thresholds"] = Thresholds(**data["thresholds"])
    return IndexConfig(**data)
