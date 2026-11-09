"""Tools tests — Sprint 1 LIVE, real PostgreSQL.

Every assertion checks numbers straight from the seeded database:
counts, filters, and VAT (exactly 15% of the invoice amount).
"""
from datetime import datetime, timezone

import pytest

from app.db import models
from app.tools import crm as crm_tools
from app.tools import erp as erp_tools
from app.tools.registry import (
    ApprovalRequiredError,
    ToolError,
    execute_tool,
)


def test_list_invoices_pending(db):
    result = erp_tools.list_invoices(db, status="PENDING")
    assert result["count"] == 12
    assert result["total_amount_sar"] == pytest.approx(581100.19, abs=0.01)
    assert result["total_vat_sar"] == pytest.approx(87165.03, abs=0.01)
    assert all(row["status"] == "PENDING" for row in result["rows"])


def test_list_invoices_vat_is_exactly_15_percent(db):
    result = erp_tools.list_invoices(db)
    assert result["count"] == 24
    for row in result["rows"]:
        assert row["vat_sar"] == pytest.approx(row["amount_sar"] * 0.15, abs=0.01)


def test_list_invoices_status_filters(db):
    assert erp_tools.list_invoices(db, status="PAID")["count"] == 6
    assert erp_tools.list_invoices(db, status="OVERDUE")["count"] == 4
    assert erp_tools.list_invoices(db, status="DISPUTED")["count"] == 2
    with pytest.raises(ValueError, match="Unknown invoice status"):
        erp_tools.list_invoices(db, status="BOGUS")


def test_list_suppliers_overdue(db):
    result = erp_tools.list_suppliers(db, overdue=True)
    assert result["count"] == 3
    total = sum(row["overdue_total_sar"] for row in result["rows"])
    assert total == pytest.approx(164941.98, abs=0.01)
    assert all(row["overdue_total_sar"] > 0 for row in result["rows"])


def test_list_suppliers_all(db):
    assert erp_tools.list_suppliers(db)["count"] == 10


def test_get_purchase_order(db):
    po = erp_tools.get_purchase_order(db, "PO-2026-2001")
    assert po["po_no"] == "PO-2026-2001"
    assert po["count"] >= 1
    assert po["total_amount_sar"] > 0
    assert po["rows"][0]["supplier"]


def test_get_purchase_order_unknown_returns_empty(db):
    po = erp_tools.get_purchase_order(db, "PO-2099-9999")
    assert po["count"] == 0
    assert po["rows"] == []


def test_list_customers(db):
    result = crm_tools.list_customers(db)
    assert result["count"] == 8


def test_list_leads_stale(db):
    result = crm_tools.list_leads(db, status="STALE")
    assert result["count"] == 4
    assert all(row["status"] == "STALE" for row in result["rows"])


def test_list_expense_claims_pending_only(db):
    result = crm_tools.list_expense_claims(db, pending_only=True)
    assert result["count"] > 0
    # Pending means awaiting a decision: PENDING or FLAGGED.
    assert all(row["status"] in ("PENDING", "FLAGGED") for row in result["rows"])
    all_claims = crm_tools.list_expense_claims(db, pending_only=False)
    assert all_claims["count"] == 10
    assert result["count"] <= all_claims["count"]


def _make_step(db, user):
    workflow = (
        db.query(models.Workflow)
        .filter(models.Workflow.key == "INVOICE_REPORT")
        .first()
    )
    assert workflow is not None, "INVOICE_REPORT workflow not seeded"
    run = models.WorkflowRun(
        workflow_id=workflow.id,
        user_id=user.id,
        instruction="test",
        status="RUNNING",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(run)
    db.commit()
    step = models.WorkflowStep(
        run_id=run.id,
        agent="data",
        step_index=0,
        action="list_invoices",
        status="RUNNING",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(step)
    db.commit()
    return run.id, step.id


def test_execute_tool_records_call(db, make_user):
    user = make_user("OPERATIONS_OFFICER")
    _, step_id = _make_step(db, user)
    result = execute_tool(
        db, user, "list_invoices", {"status": "PENDING"}, step_id
    )
    assert result["count"] == 12
    calls = db.query(models.ToolCall).filter(
        models.ToolCall.step_id == step_id
    ).all()
    assert len(calls) == 1
    assert calls[0].tool_name == "list_invoices"
    assert calls[0].status == "success"


def test_execute_tool_unknown_raises(db, make_user):
    user = make_user("OPERATIONS_OFFICER")
    _, step_id = _make_step(db, user)
    with pytest.raises(ToolError, match="Unknown tool"):
        execute_tool(db, user, "launch_rocket", {}, step_id)


def test_execute_tool_write_requires_approval_token(db, make_user):
    # approve_expense_claim is a write tool: without a human approval
    # token it must refuse and record the refusal — never execute.
    user = make_user("OPERATIONS_MANAGER")
    _, step_id = _make_step(db, user)
    with pytest.raises(ApprovalRequiredError):
        execute_tool(
            db, user, "approve_expense_claim", {"claim_id": 1}, step_id
        )
    call = db.query(models.ToolCall).filter(
        models.ToolCall.step_id == step_id
    ).first()
    assert call is not None
    assert call.status == "refused"
