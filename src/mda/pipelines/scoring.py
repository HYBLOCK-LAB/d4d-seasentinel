from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import psycopg

from mda.config import ScoringConfig, load_scoring_config
from mda.paths import config_path
from mda.pipelines.detectors import REGISTRY
from mda.pipelines.detectors.core import Detection, effective_gap_hours
from mda.store import pg

METHOD = "scoring.v2"
DEFAULT_WINDOW_HOURS = 72.0


def clip_score(x: float) -> float:
    return max(0.0, min(100.0, x))


def level_for(score: float, thresholds: dict) -> str:
    if score >= thresholds["critical"]:
        return "CRITICAL"
    if score >= thresholds["high"]:
        return "HIGH"
    return "MED"


def assemble(alert_base: dict, evidence: list[dict], thresholds: dict) -> dict:
    for e in evidence:
        e["method_version"] = METHOD
    score = clip_score(sum(e["points"] for e in evidence))
    alert = dict(alert_base)
    alert["score"] = score
    alert["level"] = level_for(score, thresholds)
    return alert


def detector_params(raw: dict) -> dict:
    return {k: v for k, v in raw.items() if k not in {"enabled", "weight"}}


def detector_weight(raw: dict) -> float:
    return float(raw.get("weight", 1.0))


def enabled_detector_names(cfg: ScoringConfig) -> list[str]:
    return [
        name
        for name, params in cfg.detectors.items()
        if params.get("enabled", True) and name in REGISTRY
    ]


def make_dedupe_key(alert_type: str, subject_id: str) -> str:
    return f"{alert_type}:{subject_id}"


def alert_type_for_subject(subject_type: str) -> str:
    if subject_type == "zone":
        return "zone_threat"
    return "vessel_threat"


def score_detections(detections: list[Detection], thresholds: dict) -> tuple[float, str]:
    score = clip_score(sum(d.points for d in detections))
    return score, level_for(score, thresholds)


def _window() -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(hours=DEFAULT_WINDOW_HOURS), end


def _apply_overrides(name: str, params: dict, min_gap_hours: float | None, cable_km: float | None) -> dict:
    params = dict(params)
    if name == "ais_gap" and min_gap_hours is not None:
        params["min_gap_hours"] = min_gap_hours
    if name == "cable_proximity" and cable_km is not None:
        params["max_km"] = cable_km
    return params


def _weighted(detections: list[Detection], weight: float) -> list[Detection]:
    return [replace(d, points=d.points * weight) for d in detections]


def _subject_region(conn: psycopg.Connection, subject_type: str, subject_id: str) -> str | None:
    try:
        with conn.cursor() as cur:
            if subject_type == "zone":
                cur.execute("select region_id from zone where zone_id = %s", (subject_id,))
            else:
                cur.execute(
                    "select region_id from ais_position where vessel_id = %s "
                    "order by ts desc limit 1",
                    (subject_id,),
                )
            row = cur.fetchone()
    except psycopg.Error:
        conn.rollback()
        return None
    return row[0] if row else None


def _titles(subject_type: str, subject_id: str, detections: list[Detection], score: float) -> tuple[str, str]:
    top_terms = [d.term for d in sorted(detections, key=lambda d: d.points, reverse=True) if d.points > 0]
    top = ", ".join(dict.fromkeys(top_terms[:3])) or "evidence mix"
    if subject_type == "zone":
        return (
            f"{subject_id} 구역 위협 점수 {score:.0f} — {top}",
            f"{subject_id} zone threat score {score:.0f} — {top}",
        )
    return (
        f"{subject_id} 선박 위협 점수 {score:.0f} — {top}",
        f"{subject_id} vessel threat score {score:.0f} — {top}",
    )


def _evidence_signature(detections: list[Detection]) -> str:
    payload = [
        {
            "term": d.term,
            "points": round(float(d.points), 6),
            "detail": d.detail,
            "src_table": d.src_table,
            "src_id": d.src_id,
        }
        for d in sorted(detections, key=lambda item: (item.term, item.src_table, item.src_id, item.detail))
    ]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return f"evidence_sha1:{hashlib.sha1(raw.encode()).hexdigest()[:16]}"


def _alert_rows(
    conn: psycopg.Connection,
    grouped: dict[tuple[str, str], list[Detection]],
    thresholds: dict,
    generated_at: datetime,
) -> tuple[list[dict], list[dict], list[dict], dict[str, int], dict[str, int]]:
    alert_rows: list[dict] = []
    evidence_rows: list[dict] = []
    history_rows: list[dict] = []
    by_type: dict[str, int] = {}
    by_subject_type: dict[str, int] = {}

    min_alert = float(thresholds.get("min_alert", 0.0))
    for (subject_type, subject_id), detections in grouped.items():
        score, level = score_detections(detections, thresholds)
        if score < min_alert:
            continue
        alert_type = alert_type_for_subject(subject_type)
        dedupe_key = make_dedupe_key(alert_type, subject_id)
        title_ko, title_en = _titles(subject_type, subject_id, detections, score)
        region_id = _subject_region(conn, subject_type, subject_id)
        terms = [d.term for d in sorted(detections, key=lambda d: d.points, reverse=True)]
        why = list(dict.fromkeys(terms))
        alert_id = f"{METHOD}:{subject_type}:{subject_id}"
        alert_rows.append(
            {
                "alert_id": alert_id,
                "alert_type": alert_type,
                "level": level,
                "vessel_id": subject_id if subject_type == "vessel" else None,
                "zone_id": subject_id if subject_type == "zone" else None,
                "region_id": region_id,
                "generated_at": generated_at,
                "method_version": METHOD,
                "score": score,
                "title_ko": title_ko,
                "title_en": title_en,
                "why": why,
                "summary_ko": None,
                "dedupe_key": dedupe_key,
                "source_id": "scoring",
                "collector": "scoring_pipeline",
                "raw_ref": _evidence_signature(detections),
            }
        )
        for d in detections:
            evidence_rows.append(
                {
                    "dedupe_key": dedupe_key,
                    "term_name": d.term,
                    "points": d.points,
                    "src_table": d.src_table,
                    "src_id": d.src_id,
                    "detail": d.detail,
                    "method_version": METHOD,
                }
            )
        history_rows.append({"dedupe_key": dedupe_key, "ts": generated_at, "score": score, "level": level})
        by_type[alert_type] = by_type.get(alert_type, 0) + 1
        by_subject_type[subject_type] = by_subject_type.get(subject_type, 0) + 1

    return alert_rows, evidence_rows, history_rows, by_type, by_subject_type


def _upsert_alerts(conn: psycopg.Connection, alert_rows: list[dict]) -> dict[str, str]:
    if not alert_rows:
        return {}
    statement = """
        insert into alert (
            alert_id, alert_type, level, vessel_id, zone_id, region_id, generated_at,
            method_version, score, title_ko, title_en, why, summary_ko, dedupe_key,
            source_id, collector, raw_ref
        ) values (
            %(alert_id)s, %(alert_type)s, %(level)s, %(vessel_id)s, %(zone_id)s, %(region_id)s,
            %(generated_at)s, %(method_version)s, %(score)s, %(title_ko)s, %(title_en)s,
            %(why)s, %(summary_ko)s, %(dedupe_key)s, %(source_id)s, %(collector)s, %(raw_ref)s
        )
        on conflict (dedupe_key) where dedupe_key is not null do update set
            alert_type = excluded.alert_type,
            level = excluded.level,
            vessel_id = excluded.vessel_id,
            zone_id = excluded.zone_id,
            region_id = excluded.region_id,
            generated_at = excluded.generated_at,
            method_version = excluded.method_version,
            score = excluded.score,
            title_ko = excluded.title_ko,
            title_en = excluded.title_en,
            why = excluded.why,
            summary_ko = case
                when alert.raw_ref is distinct from excluded.raw_ref then null
                else alert.summary_ko
            end,
            source_id = excluded.source_id,
            collector = excluded.collector,
            raw_ref = excluded.raw_ref
        returning alert_id, dedupe_key
    """
    alert_ids: dict[str, str] = {}
    with conn.cursor() as cur:
        for row in alert_rows:
            cur.execute(statement, row)
            alert_id, dedupe_key = cur.fetchone()
            alert_ids[dedupe_key] = alert_id
    return alert_ids


def _replace_evidence(conn: psycopg.Connection, evidence_rows: list[dict], alert_ids: dict[str, str]) -> int:
    if not alert_ids:
        return 0
    actual_alert_ids = list(alert_ids.values())
    with conn.cursor() as cur:
        cur.execute("delete from alert_evidence where alert_id = any(%s)", (actual_alert_ids,))
        rows = []
        for row in evidence_rows:
            alert_id = alert_ids.get(row.pop("dedupe_key"))
            if alert_id is None:
                continue
            rows.append({"alert_id": alert_id, **row})
        if rows:
            cur.executemany(
                "insert into alert_evidence "
                "(alert_id, term_name, points, src_table, src_id, detail, method_version) "
                "values (%(alert_id)s, %(term_name)s, %(points)s, %(src_table)s, %(src_id)s, %(detail)s, %(method_version)s)",
                rows,
            )
    return len(evidence_rows)


def _insert_history(conn: psycopg.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "insert into threat_score_history (dedupe_key, ts, score, level) "
            "values (%(dedupe_key)s, %(ts)s, %(score)s, %(level)s) "
            "on conflict (dedupe_key, ts) do nothing",
            rows,
        )
    return len(rows)


def _upsert_method(conn: psycopg.Connection) -> None:
    config_hash = hashlib.sha1(config_path("scoring.yaml").read_bytes()).hexdigest()[:16]
    pg.upsert(
        conn,
        "method_registry",
        [{"method_version": METHOD, "config_snapshot": json.dumps({"config_hash": config_hash})}],
        conflict=["method_version"],
        update=["config_snapshot"],
    )


def _run_detectors(
    conn: psycopg.Connection,
    cfg: ScoringConfig,
    window: tuple[datetime, datetime],
    min_gap_hours: float | None,
    cable_km: float | None,
) -> tuple[list[Detection], dict[str, int]]:
    detections: list[Detection] = []
    detector_counts: dict[str, int] = {}
    for name in enabled_detector_names(cfg):
        raw = cfg.detectors[name]
        params = _apply_overrides(name, detector_params(raw), min_gap_hours, cable_km)
        found = REGISTRY[name].func(conn, window, params)
        weighted = _weighted(found, detector_weight(raw))
        detections.extend(weighted)
        detector_counts[name] = len(weighted)
    return detections, detector_counts


def run_scoring(
    min_gap_hours: float | None = None,
    cable_km: float | None = None,
    explain: bool = False,
    top: int = 20,
) -> dict:
    cfg = load_scoring_config()
    window = _window()
    generated_at = datetime.now(timezone.utc)

    with pg.connect() as conn:
        detections, detector_counts = _run_detectors(conn, cfg, window, min_gap_hours, cable_km)
        grouped: dict[tuple[str, str], list[Detection]] = defaultdict(list)
        for detection in detections:
            grouped[(detection.subject_type, detection.subject_id)].append(detection)

        alert_rows, evidence_rows, history_rows, by_type, by_subject_type = _alert_rows(
            conn, grouped, cfg.thresholds, generated_at
        )
        _upsert_method(conn)
        alert_ids = _upsert_alerts(conn, alert_rows)
        evidence_count = _replace_evidence(conn, evidence_rows, alert_ids)
        history_count = _insert_history(conn, history_rows)
        _prune_stale_alerts(conn, list(alert_ids.keys()))

        explain_result = explain_top_alerts(conn, top) if explain else {"explained": 0, "skipped_no_evidence": 0}

    return {
        "alerts": len(alert_rows),
        "evidence": evidence_count,
        "links": 0,
        "history": history_count,
        "by_type": by_type,
        "by_subject_type": by_subject_type,
        "detectors": detector_counts,
        "explained": explain_result,
    }


def _prune_stale_alerts(conn: psycopg.Connection, live_dedupe_keys: list[str]) -> None:
    # Score history is kept so trends survive alert suppression.
    with conn.cursor() as cur:
        cur.execute(
            "select alert_id from alert where method_version = %s "
            "and not (dedupe_key = any(%s))",
            (METHOD, live_dedupe_keys or [""]),
        )
        stale = [r[0] for r in cur.fetchall()]
        if not stale:
            return
        cur.execute("delete from alert_evidence where alert_id = any(%s)", (stale,))
        cur.execute("delete from alert where alert_id = any(%s)", (stale,))


def _evidence_for_explain(conn: psycopg.Connection, alert_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "select term_name, points, detail from alert_evidence "
            "where alert_id = %s order by points desc",
            (alert_id,),
        )
        return [
            {"term": term, "points": points, "detail": detail}
            for term, points, detail in cur.fetchall()
        ]


def explain_top_alerts(conn: psycopg.Connection, top: int = 20) -> dict:
    from mda.llm_client import generate_threat_summary_ko

    with conn.cursor() as cur:
        cur.execute(
            "select alert_id, title_ko, title_en, level, score, why "
            "from alert where method_version = %s and (summary_ko is null or summary_ko = '') "
            "order by score desc nulls last limit %s",
            (METHOD, top),
        )
        alerts = cur.fetchall()

    explained = 0
    skipped_no_evidence = 0
    for alert_id, title_ko, title_en, level, score, why in alerts:
        evidence = _evidence_for_explain(conn, alert_id)
        if not evidence:
            skipped_no_evidence += 1
            continue
        summary = generate_threat_summary_ko(
            {
                "id": alert_id,
                "title_ko": title_ko,
                "title_en": title_en,
                "level": level,
                "score": score,
                "why": why,
            },
            evidence,
        )
        with conn.cursor() as cur:
            cur.execute("update alert set summary_ko = %s where alert_id = %s", (summary, alert_id))
        explained += 1
    return {"explained": explained, "skipped_no_evidence": skipped_no_evidence}
