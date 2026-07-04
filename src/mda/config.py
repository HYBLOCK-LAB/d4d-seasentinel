from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date

import yaml

from mda.paths import config_path


@dataclass
class Aoi:
    aoi_id: str
    name: str
    role: str
    bbox: list[float]
    coords_verified: bool = False
    region_id: str | None = None
    staging_for: list[str] = field(default_factory=list)
    queries: dict[str, str] = field(default_factory=dict)


@dataclass
class Region:
    region_id: str
    name: str
    bbox: list[float]
    theatre: str | None = None
    priority: str | None = None


@dataclass
class Event:
    event_id: str
    name: str
    event_date: date
    aoi_id: str
    search_days_before: int
    search_days_after: int
    event_type: str | None = None
    description: str | None = None
    citations: list[str] = field(default_factory=list)


@dataclass
class Incident:
    event_id: str
    name: str
    event_type: str
    event_date: date
    region_id: str
    lat: float
    lon: float
    description: str
    citations: list[str] = field(default_factory=list)
    vessels: list[str] = field(default_factory=list)


@dataclass
class Source:
    source_id: str
    kind: str
    enabled: bool = True
    base_url: str | None = None
    license: str | None = None
    module: str | None = None
    forecast_url: str | None = None


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


def _load_yaml(name: str):
    with config_path(name).open() as f:
        return yaml.safe_load(f)


def _build(cls, item: dict):
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in item.items() if k in known})


def load_aois() -> list[Aoi]:
    return [_build(Aoi, item) for item in _load_yaml("aois.yaml")]


def load_regions() -> list[Region]:
    return [_build(Region, item) for item in _load_yaml("regions.yaml")]


def load_events() -> list[Event]:
    return [_build(Event, item) for item in _load_yaml("events.yaml")]


def load_sources() -> list[Source]:
    return [_build(Source, item) for item in _load_yaml("sources.yaml")]


def load_incidents() -> list[Incident]:
    return [_build(Incident, item) for item in _load_yaml("incidents.yaml")]


@dataclass
class ScoringConfig:
    thresholds: dict[str, float]
    detectors: dict[str, dict]


def load_scoring_config() -> ScoringConfig:
    return _build(ScoringConfig, _load_yaml("scoring.yaml"))


def load_index_config() -> IndexConfig:
    data = _load_yaml("index.yaml")
    data["thresholds"] = Thresholds(**data["thresholds"])
    return _build(IndexConfig, data)
