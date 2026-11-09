"""Admin tests — Sprint 3 LIVE.

Covers user listing, role changes (Admin only, never your own
role), password resets (Admin only; the new password is returned
to share out-of-band — no fake email), the filterable audit log
(Admin + Operations Manager), the /audit-logs alias, and the
observability summary.
"""
from tests.conftest import login_as

ADMIN = ("admin@almadar.local", "Admin123!")
MANAGER = ("manager@almadar.local", "Manager123!")
OPS = ("ops@almadar.local", "Ops123!")


def test_list_users_admin_only(client):
    login_as(client, *ADMIN)
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["count"] == 3
    assert {u["email"] for u in data["users"]} == {
        "admin@almadar.local",
        "manager@almadar.local",
        "ops@almadar.local",
    }


def test_list_users_forbidden_for_manager(client):
    login_as(client, *MANAGER)
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 403


def test_list_users_requires_sign_in(client):
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 401


def test_change_role_works_and_is_audited(client, make_user, db):
    from app.db import models

    target = make_user("OPERATIONS_OFFICER")
    login_as(client, *ADMIN)
    r = client.put(
        f"/api/v1/admin/users/{target.email}/role", json={"role": "OPERATIONS_MANAGER"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["user"]["role"] == "OPERATIONS_MANAGER"
    assert r.json()["data"]["old_role"] == "OPERATIONS_OFFICER"
    db.refresh(target)
    assert target.role == "OPERATIONS_MANAGER"
    audit_row = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == "ROLE_CHANGE",
            models.AuditLog.resource == f"admin/users/{target.email}/role",
        )
        .order_by(models.AuditLog.id.desc())
        .first()
    )
    assert audit_row is not None
    assert audit_row.result == "SUCCESS"


def test_change_role_cannot_change_own_role(client):
    login_as(client, *ADMIN)
    r = client.put(
        "/api/v1/admin/users/admin@almadar.local/role",
        json={"role": "OPERATIONS_MANAGER"},
    )
    assert r.status_code == 403


def test_change_role_validates_role_and_user(client, make_user):
    target = make_user("OPERATIONS_OFFICER")
    login_as(client, *ADMIN)
    r = client.put(
        f"/api/v1/admin/users/{target.email}/role", json={"role": "SUPERUSER"}
    )
    assert r.status_code == 400
    r = client.put(
        "/api/v1/admin/users/nobody@almadar.local/role",
        json={"role": "OPERATIONS_MANAGER"},
    )
    assert r.status_code == 404


def test_reset_password_returns_new_password_and_it_works(client, make_user):
    target = make_user("OPERATIONS_OFFICER")
    login_as(client, *ADMIN)
    r = client.post(f"/api/v1/admin/users/{target.email}/reset-password")
    assert r.status_code == 200, r.text
    new_password = r.json()["data"]["new_password"]
    assert len(new_password) == 12
    assert any(c.isdigit() for c in new_password)
    assert any(c.isalpha() for c in new_password)
    # The new password signs in; the old one does not.
    r = login_as(client, target.email, new_password)
    assert r.status_code == 200, r.text
    r = login_as(client, target.email, "Test123!")
    assert r.status_code == 401


def test_reset_password_forbidden_for_manager(client):
    login_as(client, *MANAGER)
    r = client.post("/api/v1/admin/users/ops@almadar.local/reset-password")
    assert r.status_code == 403


def test_reset_password_unknown_user_404(client):
    login_as(client, *ADMIN)
    r = client.post("/api/v1/admin/users/nobody@almadar.local/reset-password")
    assert r.status_code == 404


def test_audit_log_list_and_filter(client):
    login_as(client, *MANAGER)
    r = client.get("/api/v1/admin/audit")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["count"] > 0
    r = client.get("/api/v1/admin/audit", params={"action": "LOGIN"})
    assert r.status_code == 200
    rows = r.json()["data"]["audit_logs"]
    assert rows, "Expected LOGIN audit rows from the test logins"
    assert all(row["action"] == "LOGIN" for row in rows)


def test_audit_log_alias_works(client):
    login_as(client, *ADMIN)
    r = client.get("/api/v1/admin/audit-logs")
    assert r.status_code == 200
    assert r.json()["data"]["count"] > 0


def test_audit_log_forbidden_for_ops(client):
    login_as(client, *OPS)
    r = client.get("/api/v1/admin/audit")
    assert r.status_code == 403


def test_observability_summary(client):
    login_as(client, *ADMIN)
    r = client.get("/api/v1/admin/observability")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "runs_total" in data
    assert "runs_by_status" in data
    assert "latency_ms" in data
    assert data["latency_ms"]["samples"] >= 0
    assert "pending_approvals" in data
    assert "tokens_total" in data
