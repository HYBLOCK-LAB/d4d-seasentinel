from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


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


def _repo_root() -> Path:
    for candidate in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError("pyproject.toml not found in any parent directory")


def _load_yaml(relative_path: str):
    path = _repo_root() / relative_path
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
