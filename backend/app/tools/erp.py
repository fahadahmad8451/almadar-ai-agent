"""ERP tools — Sprint 1, LIVE.

Read-only tools over the real PostgreSQL ERP tables. Every tool uses
parameterised SQLAlchemy queries only — the agent never builds SQL from
user text. Results are plain JSON-serialisable dicts with totals the
agent's self-check can re-compute.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models

VALID_INVOICE_STATUSES = {"PENDING", "PAID", "OVERDUE", "DISPUTED"}


def _period_bounds(db: Session, period: str) -> tuple[datetime | None, datetime | None]:
    """Periods are anchored to the data, not the wall clock: 'last_month'
    is the calendar month before the month of the latest invoice in the
    database. This keeps results repeatable across runs and environments."""
    if period in (None, "all"):
        return None, None
    latest = db.query(func.max(models.ErpInvoice.issue_date)).scalar()
    if latest is None:
        return None, None
    if period == "this_month":
        start = latest.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if latest.month == 12:
            end = latest.replace(year=latest.year + 1, month=1, day=1)
        else:
            end = latest.replace(month=latest.month + 1, day=1)
        return start, end
    if period == "last_month":
        first_this = latest.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if first_this.month == 1:
            start = first_this.replace(year=first_this.year - 1, month=12, day=1)
        else:
            start = first_this.replace(month=first_this.month - 1, day=1)
        return start, first_this
    raise ValueError(f"Unknown period: {period!r}. Use all, this_month, or last_month.")


def _invoice_row(inv: models.ErpInvoice, supplier_name: str | None) -> dict:
    return {
        "id": inv.id,
        "invoice_no": inv.invoice_no,
        "supplier": supplier_name,
        "supplier_id": inv.supplier_id,
        "amount_sar": round(inv.amount_sar, 2),
        "vat_sar": round(inv.vat_sar, 2),
        "issue_date": inv.issue_date.date().isoformat(),
        "due_date": inv.due_date.date().isoformat(),
        "status": inv.status,
        "po_no": inv.po_no,
    }


def list_invoices(db: Session, status: str | None = None, period: str = "all") -> dict:
    """List ERP invoices, optionally filtered by status and period."""
    if status is not None and status not in VALID_INVOICE_STATUSES:
        raise ValueError(f"Unknown invoice status: {status!r}.")
    query = (
        db.query(models.ErpInvoice, models.ErpSupplier.name)
        .join(models.ErpSupplier, models.ErpInvoice.supplier_id == models.ErpSupplier.id)
        .order_by(models.ErpInvoice.due_date)
    )
    if status:
        query = query.filter(models.ErpInvoice.status == status)
    start, end = _period_bounds(db, period or "all")
    if start is not None:
        query = query.filter(models.ErpInvoice.issue_date >= start)
    if end is not None:
        query = query.filter(models.ErpInvoice.issue_date < end)
    pairs = query.all()
    rows = [_invoice_row(inv, name) for inv, name in pairs]
    return {
        "rows": rows,
        "count": len(rows),
        "total_amount_sar": round(sum(r["amount_sar"] for r in rows), 2),
        "total_vat_sar": round(sum(r["vat_sar"] for r in rows), 2),
        "filters": {"status": status, "period": period or "all"},
    }


def list_suppliers(db: Session, overdue: bool = False) -> dict:
    """List suppliers. With overdue=True, only suppliers with at least
    one OVERDUE invoice, with their overdue counts and totals."""
    suppliers = db.query(models.ErpSupplier).order_by(models.ErpSupplier.name).all()
    rows = []
    for sup in suppliers:
        overdue_invoices = (
            db.query(models.ErpInvoice)
            .filter(
                models.ErpInvoice.supplier_id == sup.id,
                models.ErpInvoice.status == "OVERDUE",
            )
            .all()
        )
        if overdue and not overdue_invoices:
            continue
        rows.append(
            {
                "id": sup.id,
                "name": sup.name,
                "name_ar": sup.name_ar,
                "contact_email": sup.contact_email,
                "payment_terms": sup.payment_terms,
                "overdue_invoice_count": len(overdue_invoices),
                "overdue_total_sar": round(sum(i.amount_sar for i in overdue_invoices), 2),
                "overdue_invoice_nos": [i.invoice_no for i in overdue_invoices],
            }
        )
    return {
        "rows": rows,
        "count": len(rows),
        "filters": {"overdue": bool(overdue)},
    }


def get_purchase_order(db: Session, po_no: str) -> dict:
    """Return the invoices recorded against one purchase order number."""
    if not po_no or not str(po_no).strip():
        raise ValueError("po_no is required.")
    invoices = (
        db.query(models.ErpInvoice, models.ErpSupplier.name)
        .join(models.ErpSupplier, models.ErpInvoice.supplier_id == models.ErpSupplier.id)
        .filter(models.ErpInvoice.po_no == str(po_no).strip())
        .order_by(models.ErpInvoice.issue_date)
        .all()
    )
    rows = [_invoice_row(inv, name) for inv, name in invoices]
    return {
        "rows": rows,
        "count": len(rows),
        "total_amount_sar": round(sum(r["amount_sar"] for r in rows), 2),
        "total_vat_sar": round(sum(r["vat_sar"] for r in rows), 2),
        "po_no": str(po_no).strip(),
    }
