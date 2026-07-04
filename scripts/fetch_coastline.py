"""Fetch Natural Earth land polygons for the offline basemap.

Outputs into web/public/geo/:
- ne_50m_land.json          global land, default render
- ne_10m_east_asia.json     10m country polygons cropped to East Asia, geometry only
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "geo"
EAST_ASIA = (100.0, 0.0, 150.0, 60.0)


def _fetch(name: str) -> dict:
    with urllib.request.urlopen(f"{BASE}/{name}", timeout=120) as resp:
        return json.load(resp)


def _bbox(geom: dict) -> tuple[float, float, float, float]:
    xs, ys = [], []

    def walk(coords):
        if isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
        else:
            for c in coords:
                walk(c)

    walk(geom["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def _intersects(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    land = _fetch("ne_50m_land.geojson")
    (OUT / "ne_50m_land.json").write_text(json.dumps(land, separators=(",", ":")))
    print(f"ne_50m_land.json: {len(land['features'])} features")

    countries = _fetch("ne_10m_admin_0_countries.geojson")
    cropped = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": f["geometry"]}
            for f in countries["features"]
            if _intersects(_bbox(f["geometry"]), EAST_ASIA)
        ],
    }
    (OUT / "ne_10m_east_asia.json").write_text(json.dumps(cropped, separators=(",", ":")))
    print(f"ne_10m_east_asia.json: {len(cropped['features'])} features")


if __name__ == "__main__":
    main()
