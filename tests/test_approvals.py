"""Approval flow tests — Sprint 2 LIVE.

Covers the Approval Agent end to end: run -> PENDING approvals ->
approve executes (export file on disk, audit rows) / reject executes
nothing / no token is refused / double-approve is 409 / high-value
claims need an Admin as second approver. Runs use throwaway users
(the fixture deletes their runs, approvals, drafts and exports).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import login_as

MANAGER = ("manager@almadar.local", "Manager123!")
ADMIN = ("admin@almadar.local", "Admin123!")


def _run_workflow(client, user, key, params=None):
    login_as(client, user.email, "Test123!")
    body = {"params": params or {}}
    r = client.post(f"/api/v1/workflows/{key}/run", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _manager_client(client):
    login_as(client, *MANAGER)
    return client


def test_workflow_run_creates_pending_approvals(client, make_user):
    user = make_user("OPERATIONS_OFFICER")
    data = _run_workflow(client, user, "INVOICE_REPORT")
    assert data["status"] == "AWAITING_APPROVAL"
    assert data["approval_ids"], "Invoice report must create at least one approval"
    _manager_client(client)
    r = client.get("/api/v1/approvals")
    assert r.status_code == 200
    pending = [a for a in r.json()["data"]["approvals"] if a["id"] in data["approval_ids"]]
    assert len(pending) == len(data["approval_ids"])
    assert all(a["status"] == "PENDING" for a in pending)
    assert pending[0]["diff"]["actions"][0]["type"] == "export_report"


def test_approve_executes_export_and_completes_run(client, make_user, db):
    from app.db import models

    user = make_user("OPERATIONS_OFFICER")
    data = _run_workflow(client, user, "INVOICE_REPORT")
    approval_id = data["approval_ids"][0]
    _manager_client(client)
    r = client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["run_status"] == "COMPLETED"
    # The export really happened: a row AND a file on disk.
    export = (
        db.query(models.ReportExport)
        .filter(models.ReportExport.run_id == data["run_id"])
        .first()
    )
    assert export is not None
    assert os.path.exists(export.file_path)
    assert os.path.getsize(export.file_path) > 0
    # Audit rows prove a human approved and it executed.
    actions = {
        a.action for a in db.query(models.AuditLog).filter(
            models.AuditLog.resource == f"approvals/{approval_id}"
        ).all()
    }
    assert "APPROVE" in actions
    assert "EXECUTE" in actions
    # The run is COMPLETED now.
    r = client.get(f"/api/v1/agent/runs/{data['run_id']}")
    assert r.json()["data"]["run"]["status"] == "COMPLETED"


def test_reject_executes_nothing(client, make_user, db):
    from app.db import models

    user = make_user("OPERATIONS_OFFICER")
    data = _run_workflow(client, user, "INVOICE_REPORT")
    approval_id = data["approval_ids"][0]
    _manager_client(client)
    r = client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        json={"comment": "Totals need a second look."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["approval"]["status"] == "REJECTED"
    assert r.json()["data"]["approval"]["comment"] == "Totals need a second look."
    # Nothing executed: no export row, no file, run REJECTED.
    exports = (
        db.query(models.ReportExport)
        .filter(models.ReportExport.run_id == data["run_id"])
        .all()
    )
    assert exports == []
    r = client.get(f"/api/v1/agent/runs/{data['run_id']}")
    assert r.json()["data"]["run"]["status"] == "REJECTED"


def test_no_token_write_tool_is_refused(client, make_user, db):
    from app.db import models
    from app.tools import registry as tools_registry

    # A Operations Manager passes the role gate — so the refusal comes
    # from the missing approval token, not the role check. (An Ops
    # user is refused earlier, with "forbidden", by design.)
    manager = make_user("OPERATIONS_MANAGER")
    ops = make_user("OPERATIONS_OFFICER")
    data = _run_workflow(client, ops, "INVOICE_REPORT")
    step = (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.run_id == data["run_id"])
        .first()
    )
    assert step is not None
    with pytest.raises(tools_registry.ApprovalRequiredError):
        tools_registry.execute_tool(
            db, manager, "export_report",
            {"run_id": data["run_id"], "format": "pdf"}, step.id,
        )
    refused = (
        db.query(models.ToolCall)
        .filter(
            models.ToolCall.step_id == step.id,
            models.ToolCall.tool_name == "export_report",
            models.ToolCall.status == "refused",
        )
        .first()
    )
    assert refused is not None
    # And no export was created by the refused call.
    exports = (
        db.query(models.ReportExport)
        .filter(models.ReportExport.run_id == data["run_id"])
        .all()
    )
    assert exports == []


def test_double_approve_is_409(client, make_user):
    user = make_user("OPERATIONS_OFFICER")
    data = _run_workflow(client, user, "INVOICE_REPORT")
    approval_id = data["approval_ids"][0]
    _manager_client(client)
    r = client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert r.status_code == 200
    r = client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "already_decided"


def test_high_value_claim_needs_admin_second_approval(client, make_user, db):
    from app.db import models

    # A claim above the 10,000 SAR second-approval threshold.
    claim = models.ExpenseClaim(
        employee_name="Test Employee",
        employee_email="test.employee@almadar.local",
        category="Travel",
        amount_sar=12000.00,
        claim_date=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        receipt_attached=True,
        policy_flag=None,
        status="PENDING",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
    )
    db.add(claim)
    db.commit()
    try:
        user = make_user("OPERATIONS_OFFICER")
        data = _run_workflow(client, user, "EXPENSE_APPROVAL")
        _manager_client(client)
        r = client.get("/api/v1/approvals")
        mine = [
            a for a in r.json()["data"]["approvals"]
            if a["run_id"] == data["run_id"] and a["diff"]["actions"][0].get("claim_id") == claim.id
        ]
        assert mine, "High-value claim must get its own approval"
        approval_id = mine[0]["id"]
        # Operations Manager cannot execute it.
        r = client.post(f"/api/v1/approvals/{approval_id}/approve")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "second_approval_required"
        # Admin can.
        login_as(client, *ADMIN)
        r = client.post(f"/api/v1/approvals/{approval_id}/approve")
        assert r.status_code == 200, r.text
        db.refresh(claim)
        assert claim.status == "APPROVED"
    finally:
        db.query(models.ExpenseClaim).filter(models.ExpenseClaim.id == claim.id).delete()
        db.commit()
