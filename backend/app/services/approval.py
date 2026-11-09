"""Approval Agent — Sprint 2, LIVE.

The Approval Agent turns a run's report into approval rows and
executes actions only after a human approves. The approval token is
the approval row itself: a write tool executes only when called with
the id of a PENDING approval whose diff contains that exact action
for that run. Without a token, write tools refuse (see the tool
registry) — the gate lives in the tool layer, not just the UI.

Second approval (design decision): an expense claim above 10,000 SAR
can only be executed by an ADMIN — a Operations Manager approving it gets
403 `second_approval_required` and the approval stays pending for an
Admin.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import audit
from app.db import models
from app.services import expense_policy
from app.tools import registry as tools_registry


class ApprovalError(Exception):
    """Invalid approval state or token."""


class SecondApprovalRequired(Exception):
    """A high-value claim needs an Admin, not just a manager."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_approvals_for_run(db: Session, run: models.WorkflowRun, requested_by: models.User, report: dict) -> list[models.Approval]:
    """One approval row per item in the report's approval_items. Each
    row's diff is exactly what will execute if a manager approves."""
    created = []
    for item in report.get("approval_items") or []:
        approval = models.Approval(
            run_id=run.id,
            requested_by=requested_by.id,
            approver_id=None,
            action_summary=item["action_summary"],
            diff=item["diff"],
            status="PENDING",
            decided_at=None,
            comment=None,
        )
        db.add(approval)
        created.append(approval)
    db.commit()
    for approval in created:
        db.refresh(approval)
    return created


def verify_approval_token(db: Session, approval_id: int, run_id: int, action_type: str) -> models.Approval:
    """Check an approval token for one write action. Raises
    ApprovalError unless the approval exists, belongs to this run, is
    still PENDING, and its diff contains this action type."""
    try:
        approval_id = int(approval_id)
    except (TypeError, ValueError) as exc:
        raise ApprovalError("Invalid approval token.") from exc
    approval = db.get(models.Approval, approval_id)
    if approval is None:
        raise ApprovalError("Approval not found.")
    if approval.run_id != run_id:
        raise ApprovalError("Approval token does not belong to this run.")
    if approval.status != "PENDING":
        raise ApprovalError(f"Approval is already {approval.status.lower()}.")
    actions = (approval.diff or {}).get("actions") or []
    if not any(a.get("type") == action_type for a in actions):
        raise ApprovalError(f"Approval does not cover action {action_type!r}.")
    return approval


def _check_second_approval(db: Session, action: dict, approver: models.User) -> None:
    """High-value expense claims need an Admin as the second approver."""
    if action.get("type") != "approve_expense_claim":
        return
    claim = db.get(models.ExpenseClaim, action.get("claim_id"))
    if claim is None:
        return
    if (
        claim.amount_sar > expense_policy.SECOND_APPROVAL_THRESHOLD_SAR
        and approver.role != "ADMIN"
    ):
        raise SecondApprovalRequired(
            f"Claim #{claim.id} is {claim.amount_sar:,.2f} SAR — above the "
            f"{expense_policy.SECOND_APPROVAL_THRESHOLD_SAR:,.0f} SAR second-approval "
            "threshold. An Admin must approve it."
        )


def _prevalidate_actions(db: Session, run: models.WorkflowRun, actions: list[dict]) -> None:
    """Check every action can execute BEFORE any of them runs, so a
    failure cannot leave an approval half-executed. Raises
    ApprovalError on the first problem; nothing has executed yet."""
    for action in actions:
        action_type = action.get("type")
        if action_type == "export_report":
            fmt = action.get("format")
            if fmt not in ("pdf", "csv", "xlsx"):
                raise ApprovalError(f"Unknown export format: {fmt!r}.")
            if not (run.plan or {}).get("report"):
                raise ApprovalError("This run has no report to export.")
        elif action_type == "save_email_draft":
            draft = action.get("draft") or {}
            if not draft.get("to_email") or not draft.get("subject") or not draft.get("body"):
                raise ApprovalError("Email draft is missing to/subject/body.")
        elif action_type == "approve_expense_claim":
            claim = db.get(models.ExpenseClaim, action.get("claim_id"))
            if claim is None:
                raise ApprovalError(f"Expense claim #{action.get('claim_id')} not found.")
            if claim.status not in ("PENDING", "FLAGGED", "APPROVED"):
                raise ApprovalError(
                    f"Expense claim #{claim.id} is {claim.status} and cannot be approved."
                )
        elif action_type == "record_invoice":
            if not action.get("invoice_no"):
                raise ApprovalError("Record-invoice action is missing invoice_no.")
            supplier = db.get(models.ErpSupplier, action.get("supplier_id"))
            if supplier is None:
                raise ApprovalError(f"Supplier #{action.get('supplier_id')} not found.")
            if action.get("status") not in ("PENDING", "DISPUTED"):
                raise ApprovalError(
                    f"Record-invoice status must be PENDING or DISPUTED, got {action.get('status')!r}."
                )
            try:
                float(action.get("amount_sar"))
                float(action.get("vat_sar"))
            except (TypeError, ValueError) as exc:
                raise ApprovalError("Record-invoice amount/vat must be numbers.") from exc
            for key in ("issue_date", "due_date"):
                try:
                    datetime.strptime(str(action.get(key)), "%Y-%m-%d")
                except (ValueError, TypeError) as exc:
                    raise ApprovalError(f"Record-invoice {key} must be YYYY-MM-DD.") from exc
        else:
            raise ApprovalError(f"Unknown action type: {action_type!r}.")


def _next_step_index(db: Session, run_id: int) -> int:
    last = (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.run_id == run_id)
        .order_by(models.WorkflowStep.step_index.desc())
        .first()
    )
    return (last.step_index + 1) if last else 0


def execute_approval(db: Session, approval: models.Approval, approver: models.User) -> dict:
    """Execute the actions in an approval's diff with its token, then
    mark the approval APPROVED and the run COMPLETED. All-or-nothing:
    any failure rolls the database back and the approval stays PENDING
    so a manager can retry. Returns the execution summary."""
    if approval.status != "PENDING":
        raise ApprovalError(f"Approval is already {approval.status.lower()}.")
    run = db.get(models.WorkflowRun, approval.run_id)
    if run is None:
        raise ApprovalError("Run not found for this approval.")
    actions = (approval.diff or {}).get("actions") or []
    for action in actions:
        _check_second_approval(db, action, approver)
    _prevalidate_actions(db, run, actions)

    step = models.WorkflowStep(
        run_id=run.id,
        agent="approval_agent",
        step_index=_next_step_index(db, run.id),
        action="execute",
        input={"approval_id": approval.id, "actions": actions},
        output={},
        status="running",
        created_at=_now(),
    )
    db.add(step)
    db.commit()
    db.refresh(step)

    executed: list[dict] = []
    try:
        for action in actions:
            action_type = action["type"]
            args = {k: v for k, v in action.items() if k != "type"}
            args["run_id"] = run.id
            result = tools_registry.execute_tool(
                db, approver, _tool_for_action(action_type), args,
                step.id, approval_token=approval.id,
            )
            executed.append({"type": action_type, "result": result})
        step.status = "success"
        step.output = {"executed": [e["type"] for e in executed]}
        approval.status = "APPROVED"
        approval.approver_id = approver.id
        approval.decided_at = _now()
        run.status = "COMPLETED"
        run.finished_at = _now()
        db.commit()
    except Exception:
        db.rollback()
        step = db.get(models.WorkflowStep, step.id)
        if step is not None:
            step.status = "failed"
            db.commit()
        raise
    audit(
        db,
        user_id=approver.id,
        action="APPROVE",
        resource=f"approvals/{approval.id}",
        result="APPROVED",
        details={"run_id": run.id, "actions": [a.get("type") for a in actions]},
    )
    audit(
        db,
        user_id=approver.id,
        action="EXECUTE",
        resource=f"approvals/{approval.id}",
        result="COMPLETED",
        details={"run_id": run.id, "executed": [e["type"] for e in executed]},
    )
    return {"approval_id": approval.id, "executed": executed, "run_status": run.status}


def _tool_for_action(action_type: str) -> str:
    return {
        "export_report": "export_report",
        "save_email_draft": "save_email_draft",
        "approve_expense_claim": "approve_expense_claim",
        "record_invoice": "record_invoice",
    }[action_type]


def reject_approval(
    db: Session, approval: models.Approval, approver: models.User, comment: str | None
) -> models.Approval:
    """Reject: nothing executes. If this was the run's only pending
    approval, the run is marked REJECTED; otherwise it stays
    AWAITING_APPROVAL for its other approvals."""
    if approval.status != "PENDING":
        raise ApprovalError(f"Approval is already {approval.status.lower()}.")
    approval.status = "REJECTED"
    approval.approver_id = approver.id
    approval.decided_at = _now()
    approval.comment = comment
    # autoflush is OFF in this codebase — flush the status change
    # before counting the remaining PENDING approvals, or the count
    # still sees this approval as pending.
    db.flush()
    run = db.get(models.WorkflowRun, approval.run_id)
    if run is not None:
        remaining = (
            db.query(models.Approval)
            .filter(models.Approval.run_id == run.id, models.Approval.status == "PENDING")
            .count()
        )
        if remaining == 0 and run.status == "AWAITING_APPROVAL":
            run.status = "REJECTED"
            run.finished_at = _now()
    db.commit()
    audit(
        db,
        user_id=approver.id,
        action="REJECT",
        resource=f"approvals/{approval.id}",
        result="REJECTED",
        details={"run_id": approval.run_id, "comment": comment},
    )
    return approval
