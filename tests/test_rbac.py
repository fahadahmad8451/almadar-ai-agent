"""RBAC tests — Sprint 2 LIVE.

The hard rule: only Operations Manager / Admin may approve. An
Operations Officer gets 403, an unsigned-in caller gets 401. In
Sprint 2 the approve endpoint is live — a Manager approving a
non-existent approval gets 404 (the role gate passed, the record
simply does not exist). The full approve/reject flows are covered
in tests/test_approvals.py.
"""
from tests.conftest import login_as


def test_ops_cannot_approve(client, make_user):
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.post("/api/v1/approvals/1/approve")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_ops_cannot_reject(client, make_user):
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.post("/api/v1/approvals/1/reject")
    assert r.status_code == 403


def test_manager_passes_role_check_then_404_for_missing_approval(client, make_user):
    user = make_user("OPERATIONS_MANAGER")
    login_as(client, user.email, "Test123!")
    r = client.post("/api/v1/approvals/1/approve")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_admin_passes_role_check_then_404_for_missing_approval(client, make_user):
    user = make_user("ADMIN")
    login_as(client, user.email, "Test123!")
    r = client.post("/api/v1/approvals/1/approve")
    assert r.status_code == 404


def test_approve_requires_auth(client):
    r = client.post("/api/v1/approvals/1/approve")
    assert r.status_code == 401


def test_ops_can_instruct_but_cannot_approve(client, make_user):
    # Same user: data questions are allowed, approvals are not.
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.post(
        "/api/v1/agent/instruct",
        json={"instruction": "Show me the pending invoices"},
    )
    assert r.status_code == 200
    r = client.post("/api/v1/approvals/1/approve")
    assert r.status_code == 403
