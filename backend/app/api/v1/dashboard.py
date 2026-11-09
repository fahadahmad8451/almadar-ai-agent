"""Dashboard summary endpoint — Production (v0.8.0).

GET /dashboard/summary — one read-only call with every figure the
Dashboard home needs, computed straight from the database. It
replaces the v0.7.0 Dashboard's two instruct calls: those burned the
shared 10-runs-per-hour budget and showed cached values once the
budget was gone. This endpoint uses no agent run at all, so the
dashboard is always live. Any signed-in role may read it (read-only).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1 import approvals as approvals_api
from app.api.v1._helpers import ok
from app.api.v1.agent import _run_public
from app.core.security import get_current_user
from app.db import models
from app.db.session import get_db
from app.services import evals as eval_service

router = APIRouter()


def _money(value) -> float:
    return round(float(value or 0), 2)


@router.get("/summary")
def dashboard_summary(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Pending invoices: count, total, VAT — direct ERP query.
    pending = (
        db.query(
            func.count(models.ErpInvoice.id),
            func.coalesce(func.sum(models.ErpInvoice.amount_sar), 0),
            func.coalesce(func.sum(models.ErpInvoice.vat_sar), 0),
        )
        .filter(models.ErpInvoice.status == "PENDING")
        .one()
    )

    # Overdue suppliers: suppliers with at least one OVERDUE invoice.
    overdue_rows = (
        db.query(
            models.ErpSupplier.name,
            func.coalesce(func.sum(models.ErpInvoice.amount_sar), 0),
        )
        .join(models.ErpInvoice, models.ErpInvoice.supplier_id == models.ErpSupplier.id)
        .filter(models.ErpInvoice.status == "OVERDUE")
        .group_by(models.ErpSupplier.id, models.ErpSupplier.name)
        .order_by(func.sum(models.ErpInvoice.amount_sar).desc())
        .all()
    )

    # Pending approvals: same visibility rule as the approvals queue
    # (managers/admins see all; officers see only their own runs).
    visible = approvals_api._visible_approvals(user, db)
    pending_approvals = [a for a in visible if a.status == "PENDING"]
    top_approvals = [
        approvals_api._approval_public(a, approvals_api._workflow_key_for_run(db, a.run_id))
        for a in pending_approvals[:4]
    ]

    # Recent runs: latest 5 (officers see only their own).
    runs_query = db.query(models.WorkflowRun).order_by(models.WorkflowRun.started_at.desc())
    if user.role == "OPERATIONS_OFFICER":
        runs_query = runs_query.filter(models.WorkflowRun.user_id == user.id)
    recent = runs_query.limit(5).all()
    recent_runs = []
    for run in recent:
        item = _run_public(run)
        workflow = db.get(models.Workflow, run.workflow_id)
        item["workflow_key"] = workflow.key if workflow else None
        recent_runs.append(item)

    # Evaluations: the latest stored suite summary (None until run).
    summary = eval_service.latest_summary(db)
    evals = (
        {
            "run_at": summary["run_at"],
            "total": summary["total"],
            "passed": summary["passed"],
            "pass_rate": summary["pass_rate"],
            "latency_ms_p95": summary["latency_ms_p95"],
        }
        if summary
        else {"run_at": None, "total": 0, "passed": 0, "pass_rate": None, "latency_ms_p95": None}
    )

    return ok(
        {
            "pending_invoices": {
                "count": int(pending[0]),
                "total_sar": _money(pending[1]),
                "vat_sar": _money(pending[2]),
            },
            "overdue_suppliers": {
                "count": len(overdue_rows),
                "total_sar": _money(sum(r[1] for r in overdue_rows)),
                "names": [r[0] for r in overdue_rows[:5]],
            },
            "pending_approvals": {
                "count": len(pending_approvals),
                "top": top_approvals,
            },
            "evals": evals,
            "recent_runs": recent_runs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
