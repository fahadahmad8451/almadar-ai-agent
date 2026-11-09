"""Agent endpoints — Sprint 1, LIVE (Data Agent only).

POST /instruct runs one natural-language instruction through the
LangGraph supervisor (parse -> data agent -> self-check -> finalize)
and returns the structured answer with its trace. Report Agent and
Approval Agent arrive in later sprints; run cancellation is still 501.
Rate limit (Design section 6): 10 instruct runs per user per hour.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.supervisor import run_agent
from app.api.v1._helpers import fail, not_implemented, ok
from app.core.security import get_current_user
from app.db import models
from app.db.session import get_db

router = APIRouter()

INSTRUCT_LIMIT_PER_HOUR = 10


class InstructBody(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    language: str | None = Field(default=None, pattern="^(en|ar)$")


def _run_public(run: models.WorkflowRun) -> dict:
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "instruction": run.instruction,
        "language": run.language,
        "status": run.status,
        "confidence": run.confidence,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.post("/instruct")
def instruct(
    body: InstructBody,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    recent = (
        db.query(models.WorkflowRun)
        .filter(models.WorkflowRun.user_id == user.id, models.WorkflowRun.started_at >= since)
        .count()
    )
    if recent >= INSTRUCT_LIMIT_PER_HOUR:
        return fail(
            429,
            "rate_limited",
            "Instruct limit reached (10 runs per hour). Try again later.",
        )
    result = run_agent(db, user, body.instruction.strip(), body.language)
    return ok(result)


@router.get("/runs")
def list_runs(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.WorkflowRun).order_by(models.WorkflowRun.started_at.desc())
    if user.role == "OPERATIONS_OFFICER":
        query = query.filter(models.WorkflowRun.user_id == user.id)
    runs = query.limit(50).all()
    return ok({"runs": [_run_public(r) for r in runs], "count": len(runs)})


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.get(models.WorkflowRun, run_id)
    if run is None:
        return fail(404, "not_found", "Run not found.")
    if user.role == "OPERATIONS_OFFICER" and run.user_id != user.id:
        return fail(403, "forbidden", "You can only view your own runs.")
    return ok({"run": _run_public(run)})


@router.get("/runs/{run_id}/trace")
def get_run_trace(
    run_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.get(models.WorkflowRun, run_id)
    if run is None:
        return fail(404, "not_found", "Run not found.")
    if user.role == "OPERATIONS_OFFICER" and run.user_id != user.id:
        return fail(403, "forbidden", "You can only view your own runs.")
    steps = (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.run_id == run_id)
        .order_by(models.WorkflowStep.step_index)
        .all()
    )
    trace = []
    for step in steps:
        calls = (
            db.query(models.ToolCall)
            .filter(models.ToolCall.step_id == step.id)
            .order_by(models.ToolCall.id)
            .all()
        )
        trace.append(
            {
                "step_index": step.step_index,
                "agent": step.agent,
                "action": step.action,
                "status": step.status,
                "latency_ms": step.latency_ms,
                "input": step.input,
                "output": step.output,
                "tool_calls": [
                    {
                        "tool": c.tool_name,
                        "args": c.args,
                        "status": c.status,
                        "error": c.error,
                    }
                    for c in calls
                ],
            }
        )
    return ok({"run": _run_public(run), "trace": trace})


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return not_implemented("POST /agent/runs/{id}/cancel")
