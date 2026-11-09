"""Approval endpoints — Sprint 2, LIVE.

The Approval Agent (approve/reject + approval tokens) is live. The
queue shows what will execute (the diff) before a manager decides.
Only Operations Manager / Admin may approve or reject — an Operations
Officer gets 403, an unsigned-in caller gets 401. Approving executes
the diff through the tool layer with the approval token; rejecting
executes nothing. A second decision on an already-decided approval
returns 409.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1._helpers import fail, ok
from app.core.security import CAN_APPROVE, get_current_user, require_roles
from app.db import models
from app.db.session import get_db
from app.services import approval as approval_service

router = APIRouter()


class RejectBody(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


def _approval_public(approval: models.Approval, workflow_key: str | None) -> dict:
    return {
        "id": approval.id,
        "run_id": approval.run_id,
        "workflow_key": workflow_key,
        "action_summary": approval.action_summary,
        "diff": approval.diff,
        "status": approval.status,
        "requested_by": approval.requested_by,
        "approver_id": approval.approver_id,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "comment": approval.comment,
    }


def _workflow_key_for_run(db: Session, run_id: int) -> str | None:
    run = db.get(models.WorkflowRun, run_id)
    if run is None:
        return None
    workflow = db.get(models.Workflow, run.workflow_id)
    return workflow.key if workflow else None


def _visible_approvals(user: models.User, db: Session):
    """Approvals a user may see: managers/admins see all; Operations
    Officers see only approvals for their own runs."""
    query = db.query(models.Approval).order_by(models.Approval.id.desc())
    if user.role == "OPERATIONS_OFFICER":
        own_run_ids = [
            r.id for r in db.query(models.WorkflowRun).filter(
                models.WorkflowRun.user_id == user.id
            ).all()
        ]
        query = query.filter(models.Approval.run_id.in_(own_run_ids or [-1]))
    return query.all()


@router.get("")
def list_approvals(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    approvals = _visible_approvals(user, db)
    return ok({
        "approvals": [
            _approval_public(a, _workflow_key_for_run(db, a.run_id)) for a in approvals
        ],
        "count": len(approvals),
        "pending_count": sum(1 for a in approvals if a.status == "PENDING"),
    })


@router.get("/{approval_id}")
def get_approval(
    approval_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    approval = db.get(models.Approval, approval_id)
    if approval is None:
        return fail(404, "not_found", "Approval not found.")
    if user.role == "OPERATIONS_OFFICER":
        run = db.get(models.WorkflowRun, approval.run_id)
        if run is None or run.user_id != user.id:
            return fail(403, "forbidden", "You can only view your own approvals.")
    return ok({"approval": _approval_public(approval, _workflow_key_for_run(db, approval.run_id))})


@router.post("/{approval_id}/approve")
def approve(
    approval_id: int,
    user: models.User = Depends(require_roles(*CAN_APPROVE)),
    db: Session = Depends(get_db),
):
    approval = db.get(models.Approval, approval_id)
    if approval is None:
        return fail(404, "not_found", "Approval not found.")
    if approval.status != "PENDING":
        return fail(409, "already_decided", f"Approval is already {approval.status.lower()}.")
    try:
        result = approval_service.execute_approval(db, approval, user)
    except approval_service.SecondApprovalRequired as exc:
        return fail(403, "second_approval_required", str(exc))
    except approval_service.ApprovalError as exc:
        return fail(409, "approval_error", str(exc))
    # Do not expose absolute server paths in the API response.
    for entry in result.get("executed") or []:
        entry_result = entry.get("result") or {}
        if "file_path" in entry_result:
            entry_result["file_name"] = entry_result["file_path"].split("/")[-1]
            del entry_result["file_path"]
    return ok(result)


@router.post("/{approval_id}/reject")
def reject(
    approval_id: int,
    body: RejectBody | None = None,
    user: models.User = Depends(require_roles(*CAN_APPROVE)),
    db: Session = Depends(get_db),
):
    approval = db.get(models.Approval, approval_id)
    if approval is None:
        return fail(404, "not_found", "Approval not found.")
    if approval.status != "PENDING":
        return fail(409, "already_decided", f"Approval is already {approval.status.lower()}.")
    try:
        approval_service.reject_approval(db, approval, user, body.comment if body else None)
    except approval_service.ApprovalError as exc:
        return fail(409, "approval_error", str(exc))
    return ok({"approval": _approval_public(approval, _workflow_key_for_run(db, approval.run_id))})
