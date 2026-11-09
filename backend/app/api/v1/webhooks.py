"""n8n webhook — Sprint 3, LIVE (optional integration, Design
decisions: n8n INCLUDED as an optional trigger; APScheduler is the
primary scheduler).

POST /webhooks/n8n/trigger {schedule_id | workflow_key} triggers a
scheduled job or a workflow run from n8n. Authentication is a shared
secret in the X-Webhook-Secret header, compared against
AMH_N8N_WEBHOOK_SECRET in .env. When no secret is configured the
endpoint is disabled and returns 503 — it never triggers a run
unauthenticated. A triggered run is a normal workflow run: it stops
at AWAITING_APPROVAL and never executes anything on its own.
"""
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1._helpers import fail, ok
from app.core.config import settings
from app.core.security import get_current_user
from app.db import models
from app.db.session import get_db
from app.services import scheduler as scheduler_service

router = APIRouter()


class N8nTriggerBody(BaseModel):
    schedule_id: int | None = None
    workflow_key: str | None = None


@router.post("/n8n/trigger")
def n8n_trigger(
    body: N8nTriggerBody,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
    db: Session = Depends(get_db),
):
    secret = settings.n8n_webhook_secret
    if not secret:
        return fail(
            503,
            "webhook_not_configured",
            "The n8n webhook is disabled — set AMH_N8N_WEBHOOK_SECRET in .env to enable it.",
        )
    if x_webhook_secret != secret:
        return fail(403, "forbidden", "Invalid webhook secret.")
    if body.schedule_id is not None:
        job = db.get(models.ScheduledJob, body.schedule_id)
        if job is None:
            return fail(404, "not_found", "Schedule not found.")
        if not job.is_active:
            return fail(409, "schedule_inactive", "This schedule is not active.")
        # Webhook runs as the Admin user (system trigger), like the scheduler.
        admin = (
            db.query(models.User)
            .filter(models.User.role == "ADMIN")
            .order_by(models.User.id)
            .first()
        )
        if admin is None:
            return fail(500, "no_admin_user", "No Admin user exists to own the run.")
        result = scheduler_service.trigger_job_now(db, job, admin)
        return ok({**result, "trigger": "n8n_webhook", "schedule_id": job.id})
    if body.workflow_key:
        workflow = (
            db.query(models.Workflow)
            .filter(models.Workflow.key == body.workflow_key.upper())
            .first()
        )
        if workflow is None:
            return fail(404, "not_found", "Workflow not found.")
        if not workflow.is_active:
            return fail(409, "workflow_inactive", "This workflow is not active.")
        admin = (
            db.query(models.User)
            .filter(models.User.role == "ADMIN")
            .order_by(models.User.id)
            .first()
        )
        if admin is None:
            return fail(500, "no_admin_user", "No Admin user exists to own the run.")
        from app.services import runner as workflow_runner

        result = workflow_runner.run_workflow(
            db,
            admin,
            workflow,
            instruction=f"n8n webhook trigger: {workflow.key}",
            language="en",
            params={},
        )
        return ok({**result, "trigger": "n8n_webhook"})
    return fail(
        400,
        "invalid_params",
        "Provide schedule_id or workflow_key.",
    )
