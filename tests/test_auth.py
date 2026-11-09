"""Auth tests — Sprint 1 LIVE.

Login / refresh / logout / me against the real DB and the real
bcrypt-hashed seed passwords. Demo accounts use the .local domain,
which email-validator rejects — the login body deliberately takes a
plain string (regression test below).
"""
from tests.conftest import login_as

SEED_USERS = [
    ("admin@almadar.local", "Admin123!", "ADMIN"),
    ("manager@almadar.local", "Manager123!", "OPERATIONS_MANAGER"),
    ("ops@almadar.local", "Ops123!", "OPERATIONS_OFFICER"),
]


def test_login_success_all_roles(client):
    for email, password, role in SEED_USERS:
        fresh = client
        r = login_as(fresh, email, password)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["data"]["user"]["email"] == email
        assert body["data"]["user"]["role"] == role
        # JWT in httpOnly cookies, never in the JSON body.
        assert "amh_access" in r.cookies
        assert "amh_refresh" in r.cookies
        assert "token" not in body["data"]
        fresh.post("/api/v1/auth/logout")


def test_login_dot_local_domain_accepted(client):
    # Regression: EmailStr + email-validator reject .local domains
    # ("special-use or reserved name"). The demo accounts are .local.
    r = login_as(client, "manager@almadar.local", "Manager123!")
    assert r.status_code == 200


def test_login_wrong_password_401(client):
    r = login_as(client, "manager@almadar.local", "WrongPassword!")
    assert r.status_code == 401
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_login_unknown_user_401(client):
    r = login_as(client, "nobody@almadar.local", "Whatever123!")
    assert r.status_code == 401


def test_login_malformed_email_422(client):
    r = login_as(client, "not-an-email", "Whatever123!")
    assert r.status_code == 422


def test_me_requires_auth(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_me_after_login(client):
    login_as(client, "ops@almadar.local", "Ops123!")
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["data"]["user"]["role"] == "OPERATIONS_OFFICER"


def test_refresh_flow(client):
    login_as(client, "admin@almadar.local", "Admin123!")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200, r.text
    assert "amh_access" in r.cookies
    # The refreshed access cookie still authenticates.
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["data"]["user"]["email"] == "admin@almadar.local"


def test_logout_clears_session(client):
    login_as(client, "admin@almadar.local", "Admin123!")
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
