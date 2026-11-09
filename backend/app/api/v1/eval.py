"""Eval endpoints — Sprint 3, LIVE.

POST /eval/run — run the 12 scripted scenarios (Design section 10)
against the seeded database and write eval_results rows. Admin or
Operations Manager only. The run takes a few seconds; scenarios that
crash are recorded as failed, never fatal to the suite.
GET /eval/results — stored results, latest first.
GET /eval/summary — the latest suite's aggregate scores and targets.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1._helpers import ok
from app.core.security import CAN_APPROVE, get_current_user, require_roles
from app.db import models
from app.db.session import get_db
from app.services import evals as eval_service

router = APIRouter()


@router.post("/run")
def run_eval(
    user: models.User = Depends(require_roles(*CAN_APPROVE)),
    db: Session = Depends(get_db),
):
    summary = eval_service.run_eval_suite(db, user)
    return ok(summary)


@router.get("/results")
def eval_results(
    scenario: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.EvalResult).order_by(models.EvalResult.id.desc())
    if scenario:
        query = query.filter(models.EvalResult.scenario == scenario)
    rows = query.limit(limit).all()
    names = {s["key"]: s["name"] for s in eval_service.SCENARIOS}
    return ok(
        {
            "results": [
                {
                    "id": r.id,
                    "scenario": r.scenario,
                    "name": names.get(r.scenario, r.scenario),
                    "workflow_key": r.workflow_key,
                    "success": r.success,
                    "tool_accuracy": r.tool_accuracy,
                    "approval_compliant": r.approval_compliant,
                    "self_check_catch": r.self_check_catch,
                    "latency_ms": r.latency_ms,
                    "run_at": r.run_at.isoformat() if r.run_at else None,
                }
                for r in rows
            ],
            "count": len(rows),
        }
    )


@router.get("/summary")
def eval_summary(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    summary = eval_service.latest_summary(db)
    if summary is None:
        return ok(
            {
                "run_at": None,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "pass_rate": None,
                "tool_accuracy_avg": None,
                "approval_compliance_rate": None,
                "self_check_catch_rate": None,
                "latency_ms_p95": None,
                "results": [],
                "note": "No eval run yet — POST /eval/run to run the suite.",
            }
        )
    return ok(summary)
