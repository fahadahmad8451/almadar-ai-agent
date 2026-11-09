"""Schedule endpoints — Sprint 3, LIVE.

The three locked scheduled jobs (Design decisions, 2026-11-06):
daily invoice check 08:00, weekly CRM digest Monday 09:00,
month-end supplier summary on the 1st at 09:00 (Asia/Riyadh).
APScheduler runs them in-process (see services/scheduler.py).

GET /schedules — list jobs with workflow, cron, next run, status.
POST /schedules/{id}/run-now — Manager/Admin runs the job now, as
the requesting user (same 10/hour run limit as manual runs).
GET /schedules/{id}/runs — scheduled + manual-trigger history for
the job. Creating, editing or deleting schedules is not built yet
(the three locked jobs are seeded); those routes stay honest 501s.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1._helpers import fail, not_implemented, ok
from app.core.security import CAN_MANAGE_SCHEDULES, get_current_user, require_roles
from app.db import models
from app.db.session import get_db
from app.services import scheduler as scheduler_service

router = APIRouter()

RUN_LIMIT_PER_HOUR = 10


def _job_public(db: Session, job: models.ScheduledJob) -> dict:
    workflow = db.get(models.Workflow, job.workflow_id)
    return {
        "id": job.id,
        "workflow_id": job.workflow_id,
        "workflow_key": workflow.key if workflow else None,
        "workflow_name": workflow.name if workflow else None,
        "cron": job.cron,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        "is_active": job.is_active,
    }


@router.get("")
def list_schedules(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    jobs = db.query(models.ScheduledJob).order_by(models.ScheduledJob.id).all()
    return ok({"schedules": [_job_public(db, j) for j in jobs], "count": len(jobs)})


@router.get("/{schedule_id}/runs")
def schedule_runs(
    schedule_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(models.ScheduledJob, schedule_id)
    if job is None:
        return fail(404, "not_found", "Schedule not found.")
    runs = (
        db.query(models.WorkflowRun)
        .filter(models.WorkflowRun.workflow_id == job.workflow_id)
        .order_by(models.WorkflowRun.started_at.desc())
        .limit(50)
        .all()
    )
    history = []
    for run in runs:
        plan = run.plan or {}
        if plan.get("schedule_id") != schedule_id:
            continue
        history.append(
            {
                "id": run.id,
                "workflow_key": plan.get("workflow_key") or run.instruction,
                "trigger": plan.get("trigger"),
                "instruction": run.instruction,
                "status": run.status,
                "confidence": run.confidence,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
        )
    return ok({"schedule_id": schedule_id, "runs": history, "count": len(history)})


@router.post("/{schedule_id}/run-now")
def run_schedule_now(
    schedule_id: int,
    user: models.User = Depends(require_roles(*CAN_MANAGE_SCHEDULES)),
    db: Session = Depends(get_db),
):
    job = db.get(models.ScheduledJob, schedule_id)
    if job is None:
        return fail(404, "not_found", "Schedule not found.")
    if not job.is_active:
        return fail(409, "schedule_inactive", "This schedule is not active.")
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    recent = (
        db.query(models.WorkflowRun)
        .filter(models.WorkflowRun.user_id == user.id, models.WorkflowRun.started_at >= since)
        .count()
    )
    if recent >= RUN_LIMIT_PER_HOUR:
        return fail(
            429,
            "rate_limited",
            "Run limit reached (10 runs per hour). Try again later.",
        )
    try:
        result = scheduler_service.trigger_job_now(db, job, user)
    except ValueError as exc:
        return fail(400, "invalid_params", str(exc))
    return ok(result)


@router.post("")
def create_schedule():
    return not_implemented("POST /schedules")


@router.put("/{schedule_id}")
def update_schedule(schedule_id: int):
    return not_implemented("PUT /schedules/{id}")


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int):
    return not_implemented("DELETE /schedules/{id}")
