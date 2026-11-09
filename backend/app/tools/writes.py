"""Write tools — Sprint 2, LIVE.

These tools execute real side effects, so the registry only calls
them with a valid human approval token (see the Approval Agent).
Every function is idempotent: re-running it after a partial failure
returns the existing result instead of executing twice.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import models
from app.services import reports as reports_service


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def export_report(db: Session, run_id: int, format: str, **kwargs) -> dict:
    """Generate the export file for an approved run. If the file was
    already generated for this run and format, return the existing
    record instead of creating a duplicate."""
    run = db.get(models.WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"Run #{run_id} not found.")
    existing = (
        db.query(models.ReportExport)
        .filter(models.ReportExport.run_id == run_id, models.ReportExport.format == format)
        .order_by(models.ReportExport.id.desc())
        .first()
    )
    if existing is not None:
        return {
            "export_id": existing.id,
            "run_id": run_id,
            "format": format,
            "file_path": existing.file_path,
            "already_generated": True,
        }
    record = reports_service.export_report_file(db, run, format)
    return {
        "export_id": record.id,
        "run_id": run_id,
        "format": format,
        "file_path": record.file_path,
        "already_generated": False,
    }


def save_email_draft(db: Session, run_id: int, draft: dict, **kwargs) -> dict:
    """Save one email draft as APPROVED. Drafts are never sent — there
    is no real email sending in this project by design."""
    draft = draft or {}
    to_email = (draft.get("to_email") or "").strip()
    subject = (draft.get("subject") or "").strip()
    body = draft.get("body") or ""
    if not to_email or not subject or not body:
        raise ValueError("Email draft needs to_email, subject, and body.")
    existing = (
        db.query(models.EmailDraft)
        .filter(
            models.EmailDraft.run_id == run_id,
            models.EmailDraft.to_email == to_email,
            models.EmailDraft.subject == subject,
        )
        .first()
    )
    if existing is not None:
        return {
            "draft_id": existing.id,
            "run_id": run_id,
            "to_email": to_email,
            "subject": subject,
            "status": existing.status,
            "already_saved": True,
        }
    row = models.EmailDraft(
        run_id=run_id,
        to_email=to_email,
        subject=subject,
        body=body,
        status="APPROVED",
        created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "draft_id": row.id,
        "run_id": run_id,
        "to_email": to_email,
        "subject": subject,
        "status": "APPROVED",
        "already_saved": False,
    }


def record_invoice(
    db: Session,
    run_id: int,
    invoice_no: str,
    supplier_id: int,
    amount_sar: float,
    vat_sar: float,
    issue_date: str,
    due_date: str,
    status: str,
    po_no: str | None = None,
    **kwargs,
) -> dict:
    """Record one invoice in ERP after a manager approved the match
    report. Idempotent on invoice_no: re-approving an already-recorded
    invoice returns the existing row instead of inserting a duplicate.
    Status is PENDING for a matched invoice, DISPUTED for a mismatched
    one — the Approval Agent decides which, this tool only records."""
    if status not in ("PENDING", "DISPUTED"):
        raise ValueError(f"Cannot record an invoice with status {status!r}.")
    existing = (
        db.query(models.ErpInvoice)
        .filter(models.ErpInvoice.invoice_no == invoice_no)
        .first()
    )
    if existing is not None:
        return {
            "invoice_id": existing.id,
            "invoice_no": existing.invoice_no,
            "status": existing.status,
            "already_recorded": True,
        }
    supplier = db.get(models.ErpSupplier, supplier_id)
    if supplier is None:
        raise ValueError(f"Supplier #{supplier_id} not found.")
    try:
        issue = datetime.strptime(issue_date, "%Y-%m-%d")
        due = datetime.strptime(due_date, "%Y-%m-%d")
    except (ValueError, TypeError) as exc:
        raise ValueError("issue_date and due_date must be YYYY-MM-DD.") from exc
    row = models.ErpInvoice(
        invoice_no=invoice_no,
        supplier_id=supplier_id,
        amount_sar=round(float(amount_sar), 2),
        vat_sar=round(float(vat_sar), 2),
        issue_date=issue,
        due_date=due,
        status=status,
        po_no=po_no,
        created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "invoice_id": row.id,
        "invoice_no": row.invoice_no,
        "status": row.status,
        "already_recorded": False,
    }


def approve_expense_claim(db: Session, claim_id: int, **kwargs) -> dict:
    """Mark one expense claim APPROVED. Already-approved claims return
    their current state instead of failing, so a retried approval
    never double-executes."""
    claim = db.get(models.ExpenseClaim, claim_id)
    if claim is None:
        raise ValueError(f"Expense claim #{claim_id} not found.")
    if claim.status == "APPROVED":
        return {
            "claim_id": claim.id,
            "employee_name": claim.employee_name,
            "amount_sar": round(claim.amount_sar, 2),
            "status": "APPROVED",
            "already_approved": True,
        }
    if claim.status not in ("PENDING", "FLAGGED"):
        raise ValueError(f"Expense claim #{claim.id} is {claim.status} and cannot be approved.")
    claim.status = "APPROVED"
    db.commit()
    return {
        "claim_id": claim.id,
        "employee_name": claim.employee_name,
        "amount_sar": round(claim.amount_sar, 2),
        "status": "APPROVED",
        "already_approved": False,
    }
