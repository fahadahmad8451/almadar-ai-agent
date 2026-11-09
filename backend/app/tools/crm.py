"""CRM tools + expense-claims tool — Sprint 1, LIVE.

Read-only tools over the real PostgreSQL CRM tables (and the ERP
expense_claims table). Same rules as the ERP tools: parameterised
queries only, plain JSON results with totals.
"""
from sqlalchemy.orm import Session

from app.db import models

VALID_LEAD_STATUSES = {"NEW", "CONTACTED", "STALE", "CONVERTED", "LOST"}


def list_customers(db: Session) -> dict:
    """List all CRM customers."""
    customers = (
        db.query(models.CrmCustomer).order_by(models.CrmCustomer.last_contact_at).all()
    )
    rows = [
        {
            "id": c.id,
            "name": c.name,
            "name_ar": c.name_ar,
            "email": c.email,
            "segment": c.segment,
            "last_contact_at": c.last_contact_at.date().isoformat() if c.last_contact_at else None,
        }
        for c in customers
    ]
    return {"rows": rows, "count": len(rows)}


def list_leads(db: Session, status: str | None = None) -> dict:
    """List CRM leads, optionally filtered by status."""
    if status is not None and status not in VALID_LEAD_STATUSES:
        raise ValueError(f"Unknown lead status: {status!r}.")
    query = db.query(models.CrmLead).order_by(models.CrmLead.score.desc())
    if status:
        query = query.filter(models.CrmLead.status == status)
    leads = query.all()
    rows = [
        {
            "id": lead.id,
            "name": lead.name,
            "email": lead.email,
            "source": lead.source,
            "status": lead.status,
            "score": lead.score,
            "last_activity_at": (
                lead.last_activity_at.date().isoformat() if lead.last_activity_at else None
            ),
        }
        for lead in leads
    ]
    return {"rows": rows, "count": len(rows), "filters": {"status": status}}


def list_expense_claims(db: Session, pending_only: bool = True) -> dict:
    """List expense claims. By default only claims still awaiting a
    decision (PENDING or FLAGGED)."""
    query = db.query(models.ExpenseClaim).order_by(models.ExpenseClaim.claim_date)
    if pending_only:
        query = query.filter(models.ExpenseClaim.status.in_(("PENDING", "FLAGGED")))
    claims = query.all()
    rows = [
        {
            "id": claim.id,
            "employee_name": claim.employee_name,
            "employee_email": claim.employee_email,
            "category": claim.category,
            "amount_sar": round(claim.amount_sar, 2),
            "claim_date": claim.claim_date.date().isoformat(),
            "receipt_attached": bool(claim.receipt_attached),
            "policy_flag": claim.policy_flag,
            "status": claim.status,
        }
        for claim in claims
    ]
    return {
        "rows": rows,
        "count": len(rows),
        "total_amount_sar": round(sum(r["amount_sar"] for r in rows), 2),
        "filters": {"pending_only": bool(pending_only)},
    }
