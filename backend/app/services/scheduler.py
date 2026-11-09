"""Scheduler service — Sprint 3, LIVE.

APScheduler (in-process, Design section 11) runs the three locked
scheduled jobs: daily invoice check 08:00, weekly CRM digest Monday
09:00, month-end supplier summary on the 1st at 09:00 (Asia/Riyadh).
A scheduled run is a normal workflow run — Supervisor -> Data Agent
-> Self-Check -> Report Agent -> Approval Agent — and stops at
AWAITING_APPROVAL. It never executes anything on its own.

The scheduled job runs as the seeded Admin user (the run owner in
the database); the audit entry and the run's plan record
trigger=scheduled and the schedule id, so a scheduled run is always
distinguishable from a manual one. Manual triggers run as the
requesting user instead.
"""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.security import audit
from app.db import models
from app.db.session import SessionLocal
from app.services import runner as workflow_runner

logger = logging.getLogger(__name__)

TIMEZONE = "Asia/Riyadh"

_scheduler: BackgroundScheduler | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_CRON_DOW_NAMES = {
    "sun": 6, "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5,
}


def _convert_cron_dow(field: str) -> str:
    """Map a crontab day-of-week field to APScheduler's convention.
    Crontab: 0/7 = Sunday, 1 = Monday. APScheduler weeks start on
    Monday: 0 = Monday, 6 = Sunday. CronTrigger.from_crontab does NOT
    convert (verified 2026-11-06: "0 9 * * 1" fired on Tuesday), so
    this mapping keeps the locked "Monday 09:00" job on Monday."""
    field = field.strip().lower()
    if field in ("*", "?"):
        return field
    parts = []
    for chunk in field.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            start, end = chunk.split("-", 1)
            parts.append(f"{_convert_cron_dow(start)}-{_convert_cron_dow(end)}")
            continue
        if chunk in _CRON_DOW_NAMES:
            parts.append(str(_CRON_DOW_NAMES[chunk]))
            continue
        try:
            value = int(chunk)
        except ValueError:
            parts.append(chunk)
            continue
        parts.append(str((value - 1) % 7))
    return ",".join(parts)


def _cron_trigger(cron: str) -> CronTrigger:
    """Build a CronTrigger from a 5-field crontab expression with the
    day-of-week converted to APScheduler's Monday-first convention."""
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(f"Expected a 5-field cron expression, got {cron!r}.")
    minute, hour, day, month, dow = fields
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=_convert_cron_dow(dow),
        timezone=TIMEZONE,
    )


def next_run_after(cron: str, from_dt: datetime | None = None) -> datetime | None:
    """Next fire time of a 5-field cron expression (Asia/Riyadh),
    returned as a naive UTC datetime for storage."""
    try:
        trigger = _cron_trigger(cron)
        base = from_dt or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        nxt = trigger.get_next_fire_time(None, base)
        if nxt is None:
            return None
        return nxt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:  # noqa: BLE001 - a bad cron is reported, not fatal
        return None


def _mark_trigger(db, run_id: int, trigger: str, schedule_id: int) -> None:
    run = db.get(models.WorkflowRun, run_id)
    if run is None:
        return
    plan = dict(run.plan or {})
    plan["trigger"] = trigger
    plan["schedule_id"] = schedule_id
    run.plan = plan
    db.commit()


def run_scheduled_job(job_id: int) -> dict | None:
    """Execute one scheduled job (called by APScheduler in its own
    thread). Opens its own DB session. Returns the run summary or
    None when the job is inactive/missing. Never raises — a failed
    scheduled run is logged, not fatal to the scheduler."""
    db = SessionLocal()
    try:
        job = db.get(models.ScheduledJob, job_id)
        if job is None:
            logger.warning("Scheduled job #%s no longer exists.", job_id)
            return None
        if not job.is_active:
            logger.info("Scheduled job #%s is inactive; skipping.", job_id)
            return None
        workflow = db.get(models.Workflow, job.workflow_id)
        if workflow is None or not workflow.is_active:
            logger.warning("Scheduled job #%s has no active workflow.", job_id)
            return None
        admin = (
            db.query(models.User)
            .filter(models.User.role == "ADMIN")
            .order_by(models.User.id)
            .first()
        )
        if admin is None:
            logger.warning("No Admin user — scheduled job #%s skipped.", job_id)
            return None
        result = workflow_runner.run_workflow(
            db,
            admin,
            workflow,
            instruction=f"Scheduled run: {workflow.key} (job #{job.id})",
            language="en",
            params={},
        )
        _mark_trigger(db, result["run_id"], "scheduled", job.id)
        job.next_run_at = next_run_after(job.cron)
        db.commit()
        audit(
            db,
            user_id=admin.id,
            action="SCHEDULED_RUN",
            resource=f"schedules/{job.id}",
            result=result["status"],
            details={"run_id": result["run_id"], "workflow_key": workflow.key},
        )
        logger.info(
            "Scheduled job #%s (%s) ran as run #%s: %s.",
            job.id, workflow.key, result["run_id"], result["status"],
        )
        return result
    except Exception:  # noqa: BLE001 - the scheduler must keep running
        logger.exception("Scheduled job #%s failed.", job_id)
        return None
    finally:
        db.close()


def trigger_job_now(db, job: models.ScheduledJob, user: models.User) -> dict:
    """Manual trigger (Run now): the same pipeline, run as the
    requesting user. The run is marked trigger=manual."""
    workflow = db.get(models.Workflow, job.workflow_id)
    if workflow is None:
        raise ValueError(f"Scheduled job #{job.id} has no workflow.")
    if not workflow.is_active:
        raise ValueError(f"Workflow {workflow.key} is not active.")
    result = workflow_runner.run_workflow(
        db,
        user,
        workflow,
        instruction=f"Manual trigger: {workflow.key} (job #{job.id})",
        language="en",
        params={},
    )
    _mark_trigger(db, result["run_id"], "manual", job.id)
    audit(
        db,
        user_id=user.id,
        action="SCHEDULE_TRIGGER",
        resource=f"schedules/{job.id}",
        result=result["status"],
        details={"run_id": result["run_id"], "workflow_key": workflow.key},
    )
    return result


def is_scheduler_running() -> bool:
    """True when the in-process APScheduler is up. The monitoring
    missed-fire rule only runs while this is true."""
    return _scheduler is not None and _scheduler.running


def run_monitoring_job() -> None:
    """5-minute alert check (Monitoring v0.9.0). Runs inside the
    scheduler thread; never raises. Only registered when
    MONITORING_ALERTS_ENABLED is true (production by default)."""
    from app.core.config import settings as _settings

    from app.services import monitoring as _monitoring

    api_url = f"http://127.0.0.1:{_settings.api_port}"
    _monitoring.run_monitoring_check(api_url=api_url)


def start_scheduler() -> BackgroundScheduler | None:
    """Start the in-process scheduler and register every active job
    from the database. Fail-open: any error is logged and the app
    still serves requests (schedules stay visible, runs stay manual)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    try:
        scheduler = BackgroundScheduler(timezone=TIMEZONE)
        db = SessionLocal()
        try:
            jobs = db.query(models.ScheduledJob).filter(
                models.ScheduledJob.is_active.is_(True)
            ).all()
            for job in jobs:
                try:
                    trigger = _cron_trigger(job.cron)
                except Exception:  # noqa: BLE001 - one bad cron must not stop the rest
                    logger.warning("Scheduled job #%s has an invalid cron %r; skipped.", job.id, job.cron)
                    continue
                scheduler.add_job(
                    run_scheduled_job,
                    trigger=trigger,
                    args=[job.id],
                    id=f"scheduled-job-{job.id}",
                    replace_existing=True,
                    misfire_grace_time=300,
                )
                # Refresh the stored next run from the cron (the seed
                # writes a placeholder "tomorrow"; the API shows this
                # value, so it must be the real next fire time).
                job.next_run_at = next_run_after(job.cron)
                logger.info("Scheduled job #%s registered: %s (%s).", job.id, job.cron, TIMEZONE)
            db.commit()
        finally:
            db.close()
        scheduler.start()
        # Monitoring alert check (v0.9.0): every 5 minutes, only when
        # enabled (production by default; staging/dev stay OFF so a
        # stale database never raises alerts nobody is watching).
        if settings.monitoring_alerts_enabled:
            from apscheduler.triggers.interval import IntervalTrigger

            scheduler.add_job(
                run_monitoring_job,
                trigger=IntervalTrigger(minutes=5),
                id="monitoring-alert-check",
                replace_existing=True,
            )
            logger.info("Monitoring alert check registered (every 5 minutes).")
        _scheduler = scheduler
        return scheduler
    except Exception:  # noqa: BLE001 - scheduler failure must not kill the app
        logger.exception("Failed to start the scheduler; scheduled runs are manual-only.")
        return None


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001 - shutdown is best-effort
            logger.exception("Scheduler shutdown failed.")
        _scheduler = None
