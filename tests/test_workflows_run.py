"""Workflow run tests — Sprint 2 LIVE.

POST /workflows/{key}/run executes the full pipeline (Supervisor ->
Data Agent -> Self-Check -> Report Agent -> Approval Agent) and
stops at AWAITING_APPROVAL. All four workflows are wired. Every
step is visible on the run trace.
"""
import pytest

from tests.conftest import login_as


@pytest.mark.parametrize("key", ["INVOICE_REPORT", "SUPPLIER_FOLLOWUP", "CRM_FOLLOWUP", "EXPENSE_APPROVAL"])
def test_all_four_workflows_run_to_awaiting_approval(client, make_user, key):
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.post(f"/api/v1/workflows/{key}/run", json={"params": {}})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["workflow_key"] == key
    assert data["status"] == "AWAITING_APPROVAL"
    assert data["approval_ids"], f"{key} must create approvals"
    assert data["confidence"] is not None
    assert data["summary"]
    # The trace shows every agent in the pipeline.
    agents = {step["agent"] for step in data["trace"]}
    assert {"supervisor", "data_agent", "self_check", "report_agent", "approval_agent"} <= agents
    # The persisted run + trace show the same steps.
    r = client.get(f"/api/v1/agent/runs/{data['run_id']}/trace")
    assert r.status_code == 200
    trace_agents = {s["agent"] for s in r.json()["data"]["trace"]}
    assert {"supervisor", "data_agent", "self_check", "report_agent", "approval_agent"} <= trace_agents


def test_unknown_workflow_is_404(client, make_user):
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.post("/api/v1/workflows/NOPE/run", json={"params": {}})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_workflow_run_requires_auth(client):
    r = client.post("/api/v1/workflows/INVOICE_REPORT/run", json={"params": {}})
    assert r.status_code == 401


def test_workflow_run_with_export_format_param(client, make_user):
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.post(
        "/api/v1/workflows/INVOICE_REPORT/run",
        json={"params": {"export_format": "csv"}},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "AWAITING_APPROVAL"
    # The approval diff asks for a CSV export, not the default PDF.
    login_as(client, "manager@almadar.local", "Manager123!")
    r = client.get(f"/api/v1/approvals/{data['approval_ids'][0]}")
    assert r.status_code == 200
    actions = r.json()["data"]["approval"]["diff"]["actions"]
    assert actions[0]["format"] == "csv"
