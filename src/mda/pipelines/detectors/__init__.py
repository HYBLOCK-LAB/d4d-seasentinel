from __future__ import annotations

from mda.pipelines.detectors.core import Detection, REGISTRY, DetectorRegistration, register

# Import modules for decorator side effects.
from mda.pipelines.detectors import (  # noqa: F401
    ais_gap,
    cable_proximity,
    clustering,
    course_change,
    fishing_negative,
    friendly_flag,
    gfw_gap_event,
    loitering,
    low_density,
    north_origin,
    sanctioned,
    zone_activity,
    zone_anomaly,
)

__all__ = ["Detection", "DetectorRegistration", "REGISTRY", "register"]
