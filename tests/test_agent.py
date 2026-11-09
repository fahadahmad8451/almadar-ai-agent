"""Agent tests — Sprint 1 LIVE.

The three scripted data questions from the plan, plus Arabic and an
unknown instruction, run through the real HTTP endpoint against the
real DB. Each test logs in as its own throwaway user so the
10-runs-per-hour limit never interferes.
"""
from tests.conftest import login_as


def _instruct_as(client, make_user, role, instruction, language="en"):
    user = make_user(role)
    login_as(client, user.email, "Test123!")
    r = client.post(
        "/api/v1/agent/instruct",
        json={"instruction": instruction, "language": language},
    )
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    return r.json()["data"]


def test_instruct_pending_invoices(client, make_user):
    data = _instruct_as(
        client, make_user, "OPERATIONS_MANAGER", "Show me the pending invoices"
    )
    assert data["intent"] == "pending_invoices"
    assert data["status"] == "COMPLETED"
    assert data["confidence"] >= 0.70
    assert "list_invoices" in data["tools_used"]
    assert len(data["rows"]) == 12
    assert "581,100.19" in data["summary"]


def test_instruct_overdue_suppliers(client, make_user):
    data = _instruct_as(
        client, make_user, "OPERATIONS_MANAGER", "Who are the overdue suppliers?"
    )
    assert data["intent"] == "overdue_suppliers"
    assert data["status"] == "COMPLETED"
    assert "list_suppliers" in data["tools_used"]
    assert len(data["rows"]) == 3
    assert "164,941.98" in data["summary"]


def test_instruct_stale_leads(client, make_user):
    data = _instruct_as(
        client, make_user, "OPERATIONS_OFFICER", "How many stale leads do we have?"
    )
    assert data["intent"] == "stale_leads"
    assert data["status"] == "COMPLETED"
    assert len(data["rows"]) == 4
    assert "4" in data["summary"]


def test_instruct_arabic(client, make_user):
    data = _instruct_as(
        client,
        make_user,
        "OPERATIONS_MANAGER",
        "ما هي الفواتير المعلقة؟",
        language="ar",
    )
    assert data["intent"] == "pending_invoices"
    assert data["language"] == "ar"
    assert data["status"] == "COMPLETED"
    assert len(data["rows"]) == 12
    assert "فاتورة" in data["summary"]


def test_instruct_unknown_escalates(client, make_user):
    data = _instruct_as(
        client, make_user, "OPERATIONS_OFFICER", "What is the weather today?"
    )
    assert data["intent"] == "unknown"
    assert data["status"] == "ESCALATED"
    assert data["escalated"] is True
    assert data["confidence"] < 0.70
    assert data["tools_used"] == []


def test_instruct_requires_auth(client):
    r = client.post(
        "/api/v1/agent/instruct", json={"instruction": "Show me the pending invoices"}
    )
    assert r.status_code == 401


def test_run_trace_after_instruct(client, make_user):
    data = _instruct_as(
        client, make_user, "OPERATIONS_MANAGER", "Show me the pending invoices"
    )
    r = client.get(f"/api/v1/agent/runs/{data['run_id']}/trace")
    assert r.status_code == 200, r.text
    trace = r.json()["data"]["trace"]
    assert len(trace) >= 1
    tools = [c["tool"] for step in trace for c in step["tool_calls"]]
    assert "list_invoices" in tools


def test_workflows_list_live(client, make_user):
    user = make_user("OPERATIONS_MANAGER")
    login_as(client, user.email, "Test123!")
    r = client.get("/api/v1/workflows")
    assert r.status_code == 200, r.text
    keys = [w["key"] for w in r.json()["data"]["workflows"]]
    assert keys == [
        "INVOICE_REPORT",
        "SUPPLIER_FOLLOWUP",
        "CRM_FOLLOWUP",
        "EXPENSE_APPROVAL",
    ]


def test_workflows_list_requires_auth(client):
    r = client.get("/api/v1/workflows")
    assert r.status_code == 401
