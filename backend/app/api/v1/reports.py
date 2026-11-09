"""Report endpoints — Sprint 2, LIVE.

GET /reports lists real export files recorded in report_exports.
GET /reports/{run_id}/export downloads a PDF, CSV, or XLSX file — it
serves an existing file or generates it from the run's stored report
payload, and only for runs that are COMPLETED (an AWAITING_APPROVAL
run returns 409 approval_required). GET /drafts lists email drafts.
Only Operations Manager / Admin see all runs; an Operations Officer sees
only their own runs' exports and drafts.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.v1._helpers import fail, ok
from app.core.config import settings
from app.core.security import get_current_user
from app.db import models
from app.db.session import get_db
from app.services import reports as reports_service

router = APIRouter()

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _export_public(export: models.ReportExport, workflow_key: str | None) -> dict:
    return {
        "id": export.id,
        "run_id": export.run_id,
        "workflow_key": workflow_key,
        "format": export.format,
        "file_name": Path(export.file_path).name,
        "download_url": f"/api/v1/reports/{export.run_id}/export?format={export.format}",
        "created_at": export.created_at.isoformat() if export.created_at else None,
    }


def _workflow_key_for_run(db: Session, run_id: int) -> str | None:
    run = db.get(models.WorkflowRun, run_id)
    if run is None:
        return None
    workflow = db.get(models.Workflow, run.workflow_id)
    return workflow.key if workflow else None


def _own_run_ids(user: models.User, db: Session) -> set[int]:
    return {
        r.id for r in db.query(models.WorkflowRun).filter(
            models.WorkflowRun.user_id == user.id
        ).all()
    }


@router.get("/reports")
def list_reports(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.ReportExport).order_by(models.ReportExport.id.desc())
    if user.role == "OPERATIONS_OFFICER":
        own = _own_run_ids(user, db)
        query = query.filter(models.ReportExport.run_id.in_(own or [-1]))
    exports = query.all()
    return ok({
        "exports": [
            _export_public(e, _workflow_key_for_run(db, e.run_id)) for e in exports
        ],
        "count": len(exports),
    })


@router.get("/reports/{run_id}/export")
def download_export(
    run_id: int,
    format: str = Query(default="pdf"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if format not in reports_service.EXPORT_FORMATS:
        return fail(400, "invalid_format", f"Unknown export format: {format!r}.")
    run = db.get(models.WorkflowRun, run_id)
    if run is None:
        return fail(404, "not_found", "Run not found.")
    if user.role == "OPERATIONS_OFFICER" and run.user_id != user.id:
        return fail(403, "forbidden", "You can only download your own runs' exports.")
    if run.status != "COMPLETED":
        return fail(
            409,
            "approval_required",
            f"Run is {run.status} — exports are available only after the run completes.",
        )
    export = (
        db.query(models.ReportExport)
        .filter(models.ReportExport.run_id == run_id, models.ReportExport.format == format)
        .order_by(models.ReportExport.id.desc())
        .first()
    )
    if export is None:
        try:
            export = reports_service.export_report_file(db, run, format)
        except ValueError as exc:
            return fail(400, "invalid_params", str(exc))
    path = Path(export.file_path).resolve()
    base = Path(settings.export_dir).resolve()
    if not path.is_relative_to(base):
        return fail(500, "invalid_file", "Export file is outside the export directory.")
    if not path.exists():
        return fail(404, "not_found", "Export file not found on disk.")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[format],
        filename=path.name,
    )


@router.get("/drafts")
def list_drafts(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.EmailDraft).order_by(models.EmailDraft.id.desc())
    if user.role == "OPERATIONS_OFFICER":
        own = _own_run_ids(user, db)
        query = query.filter(models.EmailDraft.run_id.in_(own or [-1]))
    drafts = query.all()
    return ok({
        "drafts": [
            {
                "id": d.id,
                "run_id": d.run_id,
                "workflow_key": _workflow_key_for_run(db, d.run_id),
                "to_email": d.to_email,
                "subject": d.subject,
                "body": d.body,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in drafts
        ],
        "count": len(drafts),
    })


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(models.EmailDraft, draft_id)
    if draft is None:
        return fail(404, "not_found", "Draft not found.")
    if user.role == "OPERATIONS_OFFICER":
        run = db.get(models.WorkflowRun, draft.run_id)
        if run is None or run.user_id != user.id:
            return fail(403, "forbidden", "You can only view your own drafts.")
    return ok({
        "draft": {
            "id": draft.id,
            "run_id": draft.run_id,
            "workflow_key": _workflow_key_for_run(db, draft.run_id),
            "to_email": draft.to_email,
            "subject": draft.subject,
            "body": draft.body,
            "status": draft.status,
            "created_at": draft.created_at.isoformat() if draft.created_at else None,
        }
    })
