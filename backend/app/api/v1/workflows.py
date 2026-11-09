"""Workflow endpoints — Sprint 2.

GET list/detail are LIVE (seeded workflows from the real database).
POST /{key}/run is LIVE: the full pipeline (Supervisor -> Data Agent
-> Self-Check -> Report Agent -> Approval Agent) runs and stops at
AWAITING_APPROVAL — nothing executes until a manager approves.
POST /{key}/attach-pdf is LIVE (Sprint 3): an invoice PDF is
extracted, matched against its PO, and queued for approval.
All endpoints require sign-in. Workflow runs share the instruct rate
limit: 10 runs per user per hour.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1._helpers import fail, ok
from app.core.security import get_current_user
from app.db import models
from app.db.session import get_db
from app.services import invoice_upload as upload_service
from app.services import runner as workflow_runner

router = APIRouter()

RUN_LIMIT_PER_HOUR = 10


class RunBody(BaseModel):
    instruction: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, pattern="^(en|ar)$")
    params: dict | None = None


def _workflow_public(w: models.Workflow) -> dict:
    return {
        "id": w.id,
        "key": w.key,
        "name": w.name,
        "name_ar": w.name_ar,
        "description": w.description,
        "trigger_type": w.trigger_type,
        "is_active": w.is_active,
    }


@router.get("")
def list_workflows(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workflows = (
        db.query(models.Workflow).order_by(models.Workflow.id).all()
    )
    return ok({"workflows": [_workflow_public(w) for w in workflows], "count": len(workflows)})


@router.get("/{key}")
def get_workflow(
    key: str,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workflow = db.query(models.Workflow).filter(models.Workflow.key == key.upper()).first()
    if workflow is None:
        return fail(404, "not_found", "Workflow not found.")
    return ok({"workflow": _workflow_public(workflow)})


@router.post("/{key}/run")
def run_workflow(
    key: str,
    body: RunBody | None = None,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workflow = db.query(models.Workflow).filter(models.Workflow.key == key.upper()).first()
    if workflow is None:
        return fail(404, "not_found", "Workflow not found.")
    if not workflow.is_active:
        return fail(409, "workflow_inactive", "This workflow is not active.")
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
            "Workflow run limit reached (10 runs per hour). Try again later.",
        )
    try:
        result = workflow_runner.run_workflow(
            db,
            user,
            workflow,
            instruction=(body.instruction if body else None),
            language=(body.language if body else None),
            params=(body.params if body else None) or {},
        )
    except ValueError as exc:
        return fail(400, "invalid_params", str(exc))
    return ok(result)


@router.post("/{key}/attach-pdf")
async def attach_pdf(
    key: str,
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attach an invoice PDF to a workflow run (Design 5.6): the same
    extract -> PO match -> approval queue pipeline as
    POST /invoices/upload, run under this workflow."""
    workflow = db.query(models.Workflow).filter(models.Workflow.key == key.upper()).first()
    if workflow is None:
        return fail(404, "not_found", "Workflow not found.")
    filename = (file.filename or "invoice.pdf").strip() or "invoice.pdf"
    if not filename.lower().endswith(".pdf"):
        return fail(400, "invalid_file", "Only PDF files are accepted.")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        return fail(413, "file_too_large", "PDF exceeds the 10 MB limit.")
    if len(pdf_bytes) == 0:
        return fail(400, "invalid_file", "The uploaded file is empty.")
    try:
        result = upload_service.process_invoice_upload(
            db, user, pdf_bytes, filename, workflow_key=workflow.key
        )
    except ValueError as exc:
        return fail(400, "invalid_params", str(exc))
    return ok(result)
