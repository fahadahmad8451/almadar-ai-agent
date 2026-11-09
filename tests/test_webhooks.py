"""n8n webhook tests — Sprint 3 LIVE.

The webhook is disabled (503) when no shared secret is configured,
rejects a wrong secret (403), and triggers a real workflow run with
the right secret. The secret is monkeypatched on the settings object
(the endpoint reads it per request).
"""
import pytest

from app.core.config import settings


def test_webhook_disabled_without_secret(client):
    settings.n8n_webhook_secret = ""
    r = client.post(
        "/api/v1/webhooks/n8n/trigger", json={"workflow_key": "INVOICE_REPORT"}
    )
    assert r.status_code == 503


def test_webhook_rejects_wrong_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "n8n_webhook_secret", "test-secret-123")
    r = client.post(
        "/api/v1/webhooks/n8n/trigger",
        json={"workflow_key": "INVOICE_REPORT"},
        headers={"X-Webhook-Secret": "wrong-secret"},
    )
    assert r.status_code == 403


def test_webhook_triggers_workflow_with_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "n8n_webhook_secret", "test-secret-123")
    r = client.post(
        "/api/v1/webhooks/n8n/trigger",
        json={"workflow_key": "INVOICE_REPORT"},
        headers={"X-Webhook-Secret": "test-secret-123"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "AWAITING_APPROVAL"
    assert data["trigger"] == "n8n_webhook"
    assert data["approval_ids"]


def test_webhook_unknown_workflow_404(client, monkeypatch):
    monkeypatch.setattr(settings, "n8n_webhook_secret", "test-secret-123")
    r = client.post(
        "/api/v1/webhooks/n8n/trigger",
        json={"workflow_key": "NOPE"},
        headers={"X-Webhook-Secret": "test-secret-123"},
    )
    assert r.status_code == 404


def test_webhook_needs_target(client, monkeypatch):
    monkeypatch.setattr(settings, "n8n_webhook_secret", "test-secret-123")
    r = client.post(
        "/api/v1/webhooks/n8n/trigger",
        json={},
        headers={"X-Webhook-Secret": "test-secret-123"},
    )
    assert r.status_code == 400
