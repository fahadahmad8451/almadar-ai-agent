"""Schedule tests — Sprint 3 LIVE.

Covers the three locked scheduled jobs (daily 08:00, Monday 09:00,
1st 09:00, Asia/Riyadh): listing, manual trigger as the requesting
user (same pipeline, stops at AWAITING_APPROVAL), RBAC on run-now,
and per-schedule run history. The APScheduler itself is exercised
through next_run_after (cron math) — the live clock trigger is not
waited on in tests.
"""
from datetime import datetime, timezone

from tests.conftest import login_as

MANAGER = ("manager@almadar.local", "Manager123!")
ADMIN = ("admin@almadar.local", "Admin123!")
OPS = ("ops@almadar.local", "Ops123!")

LOCKED_CRONS = {"0 8 * * *", "0 9 * * 1", "0 9 1 * *"}


def test_list_schedules_returns_three_locked_jobs(client):
    login_as(client, *MANAGER)
    r = client.get("/api/v1/schedules")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["count"] == 3
    assert {s["cron"] for s in data["schedules"]} == LOCKED_CRONS
    assert {s["workflow_key"] for s in data["schedules"]} == {
        "INVOICE_REPORT",
        "CRM_FOLLOWUP",
        "SUPPLIER_FOLLOWUP",
    }
    assert all(s["is_active"] for s in data["schedules"])
    assert all(s["next_run_at"] for s in data["schedules"])


def test_list_schedules_requires_sign_in(client):
    r = client.get("/api/v1/schedules")
    assert r.status_code == 401


def _invoice_schedule_id(client) -> int:
    """Id of the INVOICE_REPORT schedule — looked up live, because
    re-seeding re-creates the jobs with new ids."""
    r = client.get("/api/v1/schedules")
    assert r.status_code == 200, r.text
    for item in r.json()["data"]["schedules"]:
        if item["workflow_key"] == "INVOICE_REPORT":
            return item["id"]
    raise AssertionError("INVOICE_REPORT schedule not found")


def test_run_now_triggers_real_workflow_run(client, make_user):
    user = make_user("OPERATIONS_MANAGER")
    login_as(client, user.email, "Test123!")
    schedule_id = _invoice_schedule_id(client)
    r = client.post(f"/api/v1/schedules/{schedule_id}/run-now")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "AWAITING_APPROVAL"
    assert data["workflow_key"] == "INVOICE_REPORT"
    assert data["approval_ids"], "Scheduled run must create approvals"
    # History shows the manual trigger.
    r = client.get(f"/api/v1/schedules/{schedule_id}/runs")
    assert r.status_code == 200
    history = r.json()["data"]["runs"]
    assert any(
        h["id"] == data["run_id"] and h["trigger"] == "manual" for h in history
    )


def test_run_now_forbidden_for_ops(client):
    login_as(client, *OPS)
    schedule_id = _invoice_schedule_id(client)
    r = client.post(f"/api/v1/schedules/{schedule_id}/run-now")
    assert r.status_code == 403


def test_run_now_unknown_schedule_404(client):
    login_as(client, *MANAGER)
    r = client.post("/api/v1/schedules/999/run-now")
    assert r.status_code == 404


def test_schedule_runs_unknown_schedule_404(client):
    login_as(client, *MANAGER)
    r = client.get("/api/v1/schedules/999/runs")
    assert r.status_code == 404


def test_next_run_after_cron_math():
    from app.services.scheduler import next_run_after

    # Monday 2026-11-09 07:00 UTC = 10:00 Riyadh. Daily 08:00 Riyadh
    # (05:00 UTC) has passed today, so the next run is tomorrow 05:00 UTC.
    base = datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc)
    nxt = next_run_after("0 8 * * *", base)
    assert nxt is not None
    assert nxt == datetime(2026, 11, 10, 5, 0)
    # Weekly Monday 09:00 Riyadh (06:00 UTC): next Monday.
    nxt = next_run_after("0 9 * * 1", base)
    assert nxt == datetime(2026, 11, 16, 6, 0)
    # Monthly 1st 09:00 Riyadh: 1 December 06:00 UTC.
    nxt = next_run_after("0 9 1 * *", base)
    assert nxt == datetime(2026, 12, 1, 6, 0)
    # A bad cron returns None instead of raising.
    assert next_run_after("not a cron") is None


def test_run_scheduled_job_function_runs_as_admin(db):
    """run_scheduled_job executes the job as the Admin user and marks
    the run trigger=scheduled."""
    from app.db import models
    from app.services import scheduler as scheduler_service

    job = (
        db.query(models.ScheduledJob)
        .join(models.Workflow, models.ScheduledJob.workflow_id == models.Workflow.id)
        .filter(models.Workflow.key == "INVOICE_REPORT")
        .order_by(models.ScheduledJob.id)
        .first()
    )
    assert job is not None
    result = scheduler_service.run_scheduled_job(job.id)
    assert result is not None
    assert result["status"] == "AWAITING_APPROVAL"
    run = db.get(models.WorkflowRun, result["run_id"])
    assert run is not None
    assert (run.plan or {}).get("trigger") == "scheduled"
    assert (run.plan or {}).get("schedule_id") == job.id
    admin = db.query(models.User).filter(models.User.role == "ADMIN").first()
    assert run.user_id == admin.id
