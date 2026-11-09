"""JWT auth + RBAC dependencies — Sprint 1.

Same hardened pattern as Project 1 v0.10: JWT (access 15 min + refresh
24 h) in httpOnly cookies, bcrypt passwords. Tokens are never stored in
localStorage. Demo accounts (the three seeded users) are disabled in
production. Weak JWT secrets fail fast in production.
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.session import get_db

PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_COOKIE = "amh_access"
REFRESH_COOKIE = "amh_refresh"
ACCESS_MINUTES = 15
REFRESH_HOURS = 24

ROLE_ADMIN = "ADMIN"
ROLE_OPERATIONS_MANAGER = "OPERATIONS_MANAGER"
ROLE_OPERATIONS_OFFICER = "OPERATIONS_OFFICER"
ALL_ROLES = (ROLE_ADMIN, ROLE_OPERATIONS_MANAGER, ROLE_OPERATIONS_OFFICER)

CAN_RUN_WORKFLOWS = ALL_ROLES
CAN_APPROVE = (ROLE_ADMIN, ROLE_OPERATIONS_MANAGER)
CAN_MANAGE_USERS = (ROLE_ADMIN,)
CAN_MANAGE_SCHEDULES = (ROLE_ADMIN, ROLE_OPERATIONS_MANAGER)
CAN_VIEW_AUDIT = (ROLE_ADMIN, ROLE_OPERATIONS_MANAGER)

# Seeded demo accounts — DEMO ONLY, disabled in production.
DEMO_EMAILS = {
    "admin@almadar.local",
    "manager@almadar.local",
    "ops@almadar.local",
}

JWT_ALGORITHM = "HS256"
_WEAK_SECRETS = {"", "CHANGE-ME-SET-A-STRONG-SECRET-IN-.env", "change-me"}


def jwt_secret() -> str:
    secret = settings.jwt_secret
    if settings.environment == "production" and (
        secret in _WEAK_SECRETS or len(secret) < 32
    ):
        raise RuntimeError(
            "Refusing to start with a weak JWT secret in production. "
            "Set a strong JWT_SECRET (32+ characters) in .env."
        )
    return secret


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return PWD.verify(plain, hashed)
    except Exception:  # noqa: BLE001 - a bad hash is a failed login, not a crash
        return False


def _encode(user_id: int, role: str, kind: str, delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "kind": kind,
        "iat": now,
        "exp": now + delta,
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def create_access_token(user: models.User) -> str:
    return _encode(user.id, user.role, "access", timedelta(minutes=ACCESS_MINUTES))


def create_refresh_token(user: models.User) -> str:
    return _encode(user.id, user.role, "refresh", timedelta(hours=REFRESH_HOURS))


def _decode(token: str, kind: str) -> dict:
    try:
        payload = jwt.decode(
            token, jwt_secret(), algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub", "kind"]}
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from exc
    if payload.get("kind") != kind:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )
    return payload


def role_from_request(request: Request) -> str | None:
    """The caller's role from the access-token cookie, without a
    database hit — used by the request-metrics middleware. Returns
    None for public/expired tokens. Never raises."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, jwt_secret(), algorithms=[JWT_ALGORITHM], options={"verify_exp": False}
        )
    except Exception:  # noqa: BLE001 - metrics must never break a request
        return None
    if payload.get("kind") != "access":
        return None
    role = payload.get("role")
    return role if isinstance(role, str) else None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """Read the access token from the httpOnly cookie (or an Authorization
    Bearer header for API clients and tests)."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in.",
        )
    payload = _decode(token, "access")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        ) from exc
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    return user


def require_roles(*roles: str):
    def _check(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not have access to this action.",
            )
        return user

    return _check


def _cookie_secure(request=None) -> bool:
    """Secure cookies only where HTTPS is real. The request's scheme
    decides (X-Forwarded-Proto wins behind a proxy); without a request,
    fall back to the environment rule. It must NOT follow the
    environment name alone: local production is plain HTTP, and a
    Secure cookie set over plain HTTP is never sent back by browsers
    or HTTP clients — that would break every authenticated call after
    login in production."""
    if request is not None:
        scheme = request.headers.get(
            "x-forwarded-proto", request.url.scheme
        ).split(",")[0].strip().lower()
        return scheme == "https"
    return settings.environment == "production"


def set_auth_cookies(response, user: models.User, request=None) -> None:
    secure = _cookie_secure(request)
    response.set_cookie(
        ACCESS_COOKIE,
        create_access_token(user),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=ACCESS_MINUTES * 60,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        create_refresh_token(user),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/api/v1/auth",
        max_age=REFRESH_HOURS * 3600,
    )


def clear_auth_cookies(response, request=None) -> None:
    # The delete must match the cookie's flags, or the browser may
    # keep the old cookie.
    secure = _cookie_secure(request)
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=secure)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth", secure=secure)


def audit(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    resource: str | None,
    result: str,
    details: dict | None = None,
    ip: str | None = None,
) -> None:
    """Append one audit row. Never raises — a failed audit write must not
    break the request it records."""
    try:
        db.add(
            models.AuditLog(
                user_id=user_id,
                action=action,
                resource=resource,
                result=result,
                details=details or {},
                ip=ip,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - audit is best-effort
        db.rollback()
