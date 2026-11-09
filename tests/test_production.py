"""Production hardening tests — v0.8.0.

Covers what Production adds over v0.7.0: security headers on every
response, the login rate limit (5 failed/min → 429 + Retry-After),
and the production fail-fast rules (weak JWT secret, wildcard CORS).
The fail-fast rules are exercised in-process by calling the validator
with a patched settings object — the real subprocess proof is in
docs/PRODUCTION.md (the production server refuses to start).
"""
import uuid

import pytest

from app.core import rate_limit
from app.core.config import Settings, validate_production_settings
from tests.conftest import login_as


@pytest.fixture(autouse=True)
def _clear_limits():
    rate_limit.reset_login_limits()
    yield
    rate_limit.reset_login_limits()


def test_security_headers_on_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "no-referrer"
    assert "content-security-policy" in r.headers
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_security_headers_on_api_response(client):
    login_as(client, "manager@almadar.local", "Manager123!")
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"


def test_health_reports_demo_accounts_enabled(client):
    # Dev (this test process) has demo accounts on; production flips
    # the same field off — the Login page hides its demo section.
    r = client.get("/health")
    assert r.json()["data"]["demo_accounts_enabled"] is True


def test_login_rate_limit_429_after_five_failures(client):
    email = f"ratelimit-{uuid.uuid4().hex[:8]}@almadar.local"
    for _ in range(5):
        r = login_as(client, email, "WrongPassword!")
        assert r.status_code == 401, r.text
    r = login_as(client, email, "WrongPassword!")
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) >= 1


def test_login_rate_limit_cleared_by_success(client, make_user):
    user = make_user("OPERATIONS_OFFICER")
    email = user.email
    for _ in range(4):
        r = login_as(client, email, "WrongPassword!")
        assert r.status_code == 401
    # A successful login clears the counter.
    r = login_as(client, email, "Test123!")
    assert r.status_code == 200
    for _ in range(4):
        r = login_as(client, email, "WrongPassword!")
        assert r.status_code == 401, r.text


def test_login_rate_limit_is_per_email(client):
    # Failures for one email do not block a different email.
    blocked_email = f"blocked-{uuid.uuid4().hex[:8]}@almadar.local"
    for _ in range(5):
        login_as(client, blocked_email, "WrongPassword!")
    assert login_as(client, blocked_email, "WrongPassword!").status_code == 429
    other = f"other-{uuid.uuid4().hex[:8]}@almadar.local"
    assert login_as(client, other, "WrongPassword!").status_code == 401


def test_production_fail_fast_weak_secret(monkeypatch):
    import app.core.config as config_module

    prod = Settings(environment="production", jwt_secret="short")
    monkeypatch.setattr(config_module, "settings", prod)
    with pytest.raises(RuntimeError, match="weak JWT secret"):
        validate_production_settings()


def test_production_fail_fast_placeholder_secret(monkeypatch):
    import app.core.config as config_module

    prod = Settings(
        environment="production",
        jwt_secret="CHANGE-ME-SET-A-STRONG-SECRET-IN-.env",
    )
    monkeypatch.setattr(config_module, "settings", prod)
    with pytest.raises(RuntimeError, match="weak JWT secret"):
        validate_production_settings()


def test_production_fail_fast_wildcard_cors(monkeypatch):
    import app.core.config as config_module

    prod = Settings(
        environment="production",
        jwt_secret="a" * 64,
        cors_origins="*",
    )
    monkeypatch.setattr(config_module, "settings", prod)
    with pytest.raises(RuntimeError, match="wildcard CORS"):
        validate_production_settings()


def test_production_settings_pass_with_strong_secret(monkeypatch):
    import app.core.config as config_module

    prod = Settings(
        environment="production",
        jwt_secret="b" * 64,
        cors_origins="http://localhost:3100,http://127.0.0.1:3100",
    )
    monkeypatch.setattr(config_module, "settings", prod)
    validate_production_settings()  # must not raise
    assert prod.debug is False


class _FakeRequest:
    def __init__(self, scheme: str, forwarded_proto: str | None = None):
        self.url = type("URL", (), {"scheme": scheme})()
        self.headers = {}
        if forwarded_proto:
            self.headers["x-forwarded-proto"] = forwarded_proto


def test_cookie_secure_follows_request_scheme_not_environment():
    # Regression (Project 1 v0.10 lesson): local production is plain
    # HTTP — a Secure cookie set over HTTP is never sent back, so
    # every authenticated call after login would 401. Secure must
    # follow the request's scheme, not the environment name.
    from app.core.security import _cookie_secure

    assert _cookie_secure(_FakeRequest("http")) is False
    assert _cookie_secure(_FakeRequest("https")) is True
    assert _cookie_secure(_FakeRequest("http", "https")) is True
    assert _cookie_secure(_FakeRequest("https", "http")) is False


def test_cookie_secure_fallback_without_request(monkeypatch):
    import app.core.security as security_module

    from app.core.security import _cookie_secure

    monkeypatch.setattr(security_module, "settings",
                        Settings(environment="production", jwt_secret="c" * 64))
    assert _cookie_secure(None) is True
    monkeypatch.setattr(security_module, "settings",
                        Settings(environment="development"))
    assert _cookie_secure(None) is False
