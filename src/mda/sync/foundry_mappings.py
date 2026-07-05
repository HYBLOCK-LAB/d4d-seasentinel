from __future__ import annotations

OBJECT_TYPES = {
    "Vessel": {"primary_key": "vessel_id", "source_table": "vessel"},
    "Facility": {"primary_key": "facility_id", "source_table": "facility"},
    "Zone": {"primary_key": "zone_id", "source_table": "zone"},
    "Event": {"primary_key": "event_id", "source_table": "event"},
    "Alert": {"primary_key": "alert_id", "source_table": "alert"},
    "Document": {"primary_key": "document_id", "source_table": "document"},
    "IndexDaily": {"primary_key": "aoi_id_date", "source_table": "index_daily"},
    "SignalDaily": {"primary_key": "aoi_id_date_signal", "source_table": "signal_daily"},
    "WeatherDaily": {"primary_key": "region_id_date", "source_table": "weather_daily"},
}


def vessel_object(row: dict) -> dict:
    return {
        "vessel_id": row["vessel_id"],
        "mmsi": row.get("mmsi"),
        "imo": row.get("imo"),
        "name": row.get("name"),
        "vessel_type": row.get("vessel_type"),
        "length_m": row.get("length_m"),
        "owner": row.get("owner"),
        "source_id": row.get("source_id"),
    }


def event_object(row: dict) -> dict:
    return {
        "event_id": row["event_id"],
        "name": row.get("name"),
        "event_type": row.get("event_type"),
        "event_date": row["event_date"].isoformat() if row.get("event_date") else None,
        "region_id": row.get("region_id"),
        "description": row.get("description"),
        "citations": row.get("citations"),
    }


def alert_object(row: dict) -> dict:
    return {
        "alert_id": row["alert_id"],
        "alert_type": row.get("alert_type"),
        "level": row.get("level"),
        "vessel_id": row.get("vessel_id"),
        "zone_id": row.get("zone_id"),
        "region_id": row.get("region_id"),
        "generated_at": row["generated_at"].isoformat() if row.get("generated_at") else None,
        "score": float(row["score"]) if row.get("score") is not None else None,
        "method_version": row.get("method_version"),
        "title_en": row.get("title_en"),
        "why": list(row.get("why") or []),
        "title_ko": row.get("title_ko"),
        "summary_ko": row.get("summary_ko"),
        "dedupe_key": row.get("dedupe_key"),
    }


def document_object(row: dict) -> dict:
    return {
        "document_id": row["document_id"],
        "doc_type": row.get("doc_type"),
        "title": row.get("title"),
        "lang": row.get("lang"),
        "url": row.get("url"),
        "source_id": row.get("source_id"),
        "raw_ref": row.get("raw_ref"),
    }


def index_daily_object(row: dict) -> dict:
    return {
        "aoi_id_date": f"{row['aoi_id']}|{row['date'].isoformat()}|{row['method_version']}",
        "aoi_id": row["aoi_id"],
        "date": row["date"].isoformat(),
        "index_value": float(row["index_value"]) if row.get("index_value") is not None else None,
        "level": row.get("level"),
        "method_version": row.get("method_version"),
    }
