from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET

import httpx

from mda.config import load_incidents
from mda.store import pg

OFAC_SDN = "https://www.treasury.gov/ofac/downloads/sdn.csv"
UN_CONSOLIDATED = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
WPI_QUERY = "https://services1.arcgis.com/VwarAUbcaX64Jhub/arcgis/rest/services/World_Port_Index/FeatureServer/0/query"
CABLES_GEOJSON = "https://www.submarinecablemap.com/api/v3/cable/cable-geo.json"

_IMO_RE = re.compile(r"IMO\s*(?:number:?\s*)?(\d{7})", re.IGNORECASE)


def _get(url: str, params: dict | None = None) -> httpx.Response:
    resp = httpx.get(url, params=params, follow_redirects=True, timeout=120.0)
    resp.raise_for_status()
    return resp


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return None if value in ("", "-0-") else value


def collect_ofac() -> dict:
    text = _get(OFAC_SDN).text
    vessels, documents = {}, {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 12 or (row[2] or "").strip().lower() != "vessel":
            continue
        ent_num = row[0].strip()
        name = _blank(row[1])
        remarks = _blank(row[11]) or ""
        imo_match = _IMO_RE.search(remarks)
        imo = int(imo_match.group(1)) if imo_match else None
        vessel_id = f"imo:{imo}" if imo else f"sdn:{ent_num}"
        vessels[vessel_id] = {
            "vessel_id": vessel_id,
            "mmsi": None,
            "imo": imo,
            "name": name,
            "vessel_type": _blank(row[6]),
            "length_m": None,
            "owner": _blank(row[10]),
            "source_id": "ofac_sdn",
            "collector": "reference_ofac",
            "raw_ref": f"sdn:{ent_num}",
        }
        documents[f"ofac:{ent_num}"] = {
            "document_id": f"ofac:{ent_num}",
            "doc_type": "sanctions_entry",
            "title": (name or "OFAC SDN")[:200],
            "lang": "en",
            "url": OFAC_SDN,
            "published_at": None,
            "text_excerpt": remarks[:2000] or None,
            "sha256": None,
            "region_id": None,
            "source_id": "ofac_sdn",
            "collector": "reference_ofac",
            "raw_ref": f"sdn:{ent_num}",
        }
    with pg.connect() as conn:
        pg.upsert(conn, "vessel", list(vessels.values()), conflict=["vessel_id"], update=["name", "imo", "vessel_type", "owner"])
        pg.upsert(conn, "document", list(documents.values()), conflict=["document_id"], update=["title", "text_excerpt"])
    return {"ofac_vessels": len(vessels), "ofac_documents": len(documents)}


def _un_text(entity: ET.Element, tag: str) -> str:
    node = entity.find(tag)
    return node.text.strip() if node is not None and node.text else ""


def collect_un1718() -> dict:
    xml = _get(UN_CONSOLIDATED).text
    root = ET.fromstring(xml)
    vessels, documents = {}, {}
    for entity in root.iter("ENTITY"):
        if _un_text(entity, "UN_LIST_TYPE") != "DPRK":
            continue
        ref = _un_text(entity, "REFERENCE_NUMBER") or _un_text(entity, "DATAID")
        comments = _un_text(entity, "COMMENTS1")
        name = _un_text(entity, "FIRST_NAME")
        imo_match = _IMO_RE.search(comments)
        if not imo_match:
            continue
        imo = int(imo_match.group(1))
        vessel_id = f"imo:{imo}"
        vessels[vessel_id] = {
            "vessel_id": vessel_id,
            "mmsi": None,
            "imo": imo,
            "name": name[:200] or None,
            "vessel_type": None,
            "length_m": None,
            "owner": None,
            "source_id": "un1718",
            "collector": "reference_un1718",
            "raw_ref": ref,
        }
        documents[f"un:{ref}"] = {
            "document_id": f"un:{ref}",
            "doc_type": "sanctions_entry",
            "title": (name or "UN 1718")[:200],
            "lang": "en",
            "url": UN_CONSOLIDATED,
            "published_at": None,
            "text_excerpt": comments[:2000] or None,
            "sha256": None,
            "region_id": None,
            "source_id": "un1718",
            "collector": "reference_un1718",
            "raw_ref": ref,
        }
    with pg.connect() as conn:
        pg.upsert(conn, "vessel", list(vessels.values()), conflict=["vessel_id"], update=["name", "imo"])
        pg.upsert(conn, "document", list(documents.values()), conflict=["document_id"], update=["title", "text_excerpt"])
    return {"un1718_vessels": len(vessels), "un1718_documents": len(documents)}


def collect_wpi() -> dict:
    rows, offset = {}, 0
    while True:
        payload = _get(
            WPI_QUERY,
            {
                "where": "1=1",
                "outFields": "PORT_NAME,COUNTRY,LATITUDE,LONGITUDE,INDEX_NO",
                "f": "geojson",
                "resultOffset": offset,
                "resultRecordCount": 2000,
            },
        ).json()
        features = payload.get("features", [])
        if not features:
            break
        for feat in features:
            props = feat.get("properties", {})
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates")
            if not coords:
                continue
            lon, lat = coords[0], coords[1]
            index_no = props.get("INDEX_NO") or f"{lon}_{lat}"
            fid = f"wpi:{index_no}"
            rows[fid] = {
                "facility_id": fid,
                "name": props.get("PORT_NAME"),
                "name_ko": None,
                "kind": "port",
                "geom": f"SRID=4326;POINT({lon} {lat})",
                "country": props.get("COUNTRY"),
                "source_id": "world_port_index",
                "collector": "reference_wpi",
                "raw_ref": str(index_no),
            }
        if len(features) < 2000:
            break
        offset += 2000
    with pg.connect() as conn:
        pg.upsert(conn, "facility", list(rows.values()), conflict=["facility_id"], update=["name", "kind", "geom", "country"])
    return {"wpi_ports": len(rows)}


def _multiline_ewkt(geometry: dict) -> str | None:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return None
    if gtype == "LineString":
        parts = [coords]
    elif gtype == "MultiLineString":
        parts = coords
    else:
        return None
    lines = ", ".join("(" + ", ".join(f"{p[0]} {p[1]}" for p in line) + ")" for line in parts if line)
    return f"SRID=4326;MULTILINESTRING({lines})" if lines else None


def collect_cables() -> dict:
    payload = _get(CABLES_GEOJSON).json()
    rows = {}
    for feat in payload.get("features", []):
        props = feat.get("properties", {})
        ewkt = _multiline_ewkt(feat.get("geometry") or {})
        if not ewkt:
            continue
        cid = props.get("id") or props.get("feature_id")
        zone_id = f"cable:{cid}"
        rows[zone_id] = {
            "zone_id": zone_id,
            "name": props.get("name"),
            "kind": "cable",
            "role": None,
            "region_id": None,
            "geom": ewkt,
            "source_id": "telegeography_cables",
            "collector": "reference_cables",
            "raw_ref": str(cid),
        }
    with pg.connect() as conn:
        pg.upsert(conn, "zone", list(rows.values()), conflict=["zone_id"], update=["name", "kind", "geom"])
    return {"cables": len(rows)}


def collect_incidents() -> dict:
    rows = [
        {
            "event_id": inc.event_id,
            "name": inc.name,
            "event_type": inc.event_type,
            "event_date": inc.event_date,
            "zone_id": None,
            "aoi_id": None,
            "region_id": inc.region_id,
            "geom": f"SRID=4326;POINT({inc.lon} {inc.lat})",
            "description": inc.description,
            "citations": inc.citations or None,
            "source_id": "curated_incident",
            "collector": "reference_incidents",
            "raw_ref": "config/incidents.yaml",
        }
        for inc in load_incidents()
    ]
    with pg.connect() as conn:
        pg.upsert(
            conn,
            "event",
            rows,
            conflict=["event_id"],
            update=["name", "event_type", "event_date", "region_id", "geom", "description", "citations"],
        )
    return {"incidents": len(rows)}


def collect_all() -> dict:
    result = {}
    for fn in (collect_incidents, collect_ofac, collect_un1718, collect_wpi, collect_cables):
        try:
            result.update(fn())
        except Exception as exc:
            result[fn.__name__] = f"error: {type(exc).__name__}: {exc}"
    return result
