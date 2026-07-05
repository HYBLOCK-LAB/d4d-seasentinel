from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mda.config import load_scoring_config
from mda.store import pg

METHOD = "analyst.v1"
ACTION_POINTS = {"dismiss": -40.0, "lower": -20.0, "raise": 15.0}
TERM_NAME = "ANALYST_ASSESSMENT"

router = APIRouter()


class AssessRequest(BaseModel):
    action: str
    reason: str
    author: str | None = None
    raw_text: str | None = None


def resolve_level(score: float, thresholds: dict) -> str:
    if score >= thresholds["critical"]:
        return "CRITICAL"
    if score >= thresholds["high"]:
        return "HIGH"
    return "MED"


def clip_score(total: float) -> float:
    return max(0.0, min(100.0, total))


def recompute_alert(conn, alert_id: str, thresholds: dict) -> tuple[float, str]:
    with conn.cursor() as cur:
        cur.execute(
            "select coalesce(sum(points), 0) from alert_evidence where alert_id = %s",
            (alert_id,),
        )
        total = float(cur.fetchone()[0])
        score = clip_score(total)
        level = resolve_level(score, thresholds)
        cur.execute(
            "update alert set score = %s, level = %s where alert_id = %s",
            (score, level, alert_id),
        )
    return score, level


def _insert_evidence(cur, alert_id: str, assessment_id, points: float, reason: str) -> None:
    cur.execute(
        "insert into alert_evidence "
        "(alert_id, term_name, points, src_table, src_id, detail, method_version) "
        "values (%s, %s, %s, 'analyst_assessment', %s, %s, %s)",
        (alert_id, TERM_NAME, points, str(assessment_id), reason, METHOD),
    )


def apply_assessments(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "select a.assessment_id, a.alert_id, a.points, a.reason "
            "from analyst_assessment a "
            "join alert al on al.alert_id = a.alert_id "
            "where not exists ("
            "  select 1 from alert_evidence e "
            "  where e.src_table = 'analyst_assessment' and e.src_id = a.assessment_id::text"
            ")"
        )
        missing = cur.fetchall()
        for assessment_id, alert_id, points, reason in missing:
            _insert_evidence(cur, alert_id, assessment_id, points, reason)
    if missing:
        thresholds = load_scoring_config().thresholds
        for alert_id in {row[1] for row in missing}:
            recompute_alert(conn, alert_id, thresholds)
    return len(missing)


@router.post("/threats/{threat_id}/assess")
def assess_threat(threat_id: str, request: AssessRequest) -> dict:
    points = ACTION_POINTS.get(request.action)
    if points is None:
        raise HTTPException(status_code=422, detail=f"unknown action: {request.action}")
    if not request.reason.strip():
        raise HTTPException(status_code=422, detail="reason required")
    thresholds = load_scoring_config().thresholds
    with pg.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select 1 from alert where alert_id = %s", (threat_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="alert not found — 선박/존 경보만 조정할 수 있습니다",
                )
            cur.execute(
                "insert into analyst_assessment (alert_id, points, reason, raw_text, author) "
                "values (%s, %s, %s, %s, %s) returning assessment_id",
                (threat_id, points, request.reason, request.raw_text, request.author),
            )
            assessment_id = cur.fetchone()[0]
            _insert_evidence(cur, threat_id, assessment_id, points, request.reason)
        score, level = recompute_alert(conn, threat_id, thresholds)
    return {
        "alert_id": threat_id,
        "assessment_id": assessment_id,
        "action": request.action,
        "points": points,
        "score": score,
        "level": level,
    }


@router.get("/threats/{threat_id}/assessments")
def list_assessments(threat_id: str) -> dict:
    with pg.connect(readonly=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select assessment_id, points, reason, author, created_at "
                "from analyst_assessment where alert_id = %s order by created_at desc",
                (threat_id,),
            )
            rows = cur.fetchall()
    return {
        "items": [
            {
                "assessment_id": assessment_id,
                "points": points,
                "reason": reason,
                "author": author,
                "created_at": created_at.isoformat(),
            }
            for assessment_id, points, reason, author, created_at in rows
        ]
    }
