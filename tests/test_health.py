"""Baseline tests — Sprint 3 v0.4.

Health is live, and so are auth, instruct, workflows, approvals,
reports, schedules, admin, evals and invoice upload (their own test
files cover them). These tests assert the live surface — so a faked
success or a missing endpoint fails loudly.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"] == "0.9.0"
    assert body["data"]["service"] == "almadar-ai-agent"


def test_api_health_ok():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_approvals_list_is_live(client):
    # The Approval Agent is LIVE in Sprint 2: a signed-in manager
    # sees the queue (200, envelope-shaped) instead of 501.
    from tests.conftest import login_as

    login_as(client, "manager@almadar.local", "Manager123!")
    r = client.get("/api/v1/approvals")
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert "approvals" in r.json()["data"]


def test_reports_list_is_live(client):
    # The Report Agent is LIVE in Sprint 2: a signed-in manager
    # sees the exports list (200, envelope-shaped).
    from tests.conftest import login_as

    login_as(client, "manager@almadar.local", "Manager123!")
    r = client.get("/api/v1/reports")
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert "exports" in r.json()["data"]


def test_schedules_list_is_live(client):
    # The scheduler is LIVE in Sprint 3: a signed-in manager sees
    # the three locked jobs (200, envelope-shaped); unsigned-in
    # callers get 401, not a 501.
    from tests.conftest import login_as

    r = client.get("/api/v1/schedules")
    assert r.status_code == 401
    login_as(client, "manager@almadar.local", "Manager123!")
    r = client.get("/api/v1/schedules")
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert r.json()["data"]["count"] == 3
