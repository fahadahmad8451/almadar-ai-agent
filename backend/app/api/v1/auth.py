"""Auth endpoints — Sprint 1, LIVE.

JWT (access 15 min + refresh 24 h) in httpOnly cookies, bcrypt
passwords — same hardened pattern as Project 1 v0.10. Tokens are never
stored in localStorage. Demo accounts (the three seeded users) are
disabled in production. Registration (Admin creates users) arrives in
a later sprint.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1._helpers import fail, not_implemented, ok
from app.core.config import settings
from app.core.rate_limit import (
    clear_login_failures,
    login_blocked_seconds,
    record_login_failure,
)
from app.core.security import (
    CAN_MANAGE_USERS,
    DEMO_EMAILS,
    REFRESH_COOKIE,
    _decode,
    audit,
    clear_auth_cookies,
    get_current_user,
    require_roles,
    set_auth_cookies,
    verify_password,
)
from app.db import models
from app.db.session import get_db

router = APIRouter()


class LoginBody(BaseModel):
    # Plain str, not EmailStr: the demo accounts use the .local domain
    # (manager@almadar.local), which email-validator rejects as a
    # reserved special-use domain.
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def _must_look_like_email(cls, value: str) -> str:
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("Enter a valid email address.")
        return value


def _user_public(user: models.User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ip = request.client.host if request.client else "unknown"
    # Rate limit: 5 failed logins per 60 s per (IP, email) → 429 with
    # Retry-After. Only failures count; a success clears the counter.
    blocked = login_blocked_seconds(ip, email)
    if blocked is not None:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(blocked)},
            content={
                "success": False,
                "data": None,
                "error": {
                    "code": "rate_limited",
                    "message": f"Too many failed sign-in attempts. Try again in {blocked} seconds.",
                },
                "request_id": "",
            },
        )
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None or not verify_password(body.password, user.password_hash):
        record_login_failure(ip, email)
        audit(
            db,
            user_id=user.id if user else None,
            action="LOGIN",
            resource="auth/login",
            result="FAILED",
            details={"email": email},
            ip=request.client.host if request.client else None,
        )
        return fail(401, "invalid_credentials", "Email or password is incorrect.")
    if settings.environment == "production" and email in DEMO_EMAILS:
        audit(
            db,
            user_id=user.id,
            action="LOGIN",
            resource="auth/login",
            result="DENIED",
            details={"reason": "demo account disabled in production"},
        )
        return fail(401, "demo_disabled", "Demo accounts are disabled in production.")
    response = ok({"user": _user_public(user)})
    set_auth_cookies(response, user, request)
    clear_login_failures(ip, email)
    audit(
        db,
        user_id=user.id,
        action="LOGIN",
        resource="auth/login",
        result="SUCCESS",
        ip=request.client.host if request.client else None,
    )
    return response


@router.post("/refresh")
def refresh(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        return fail(401, "not_signed_in", "No refresh token. Sign in again.")
    payload = _decode(token, "refresh")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return fail(401, "invalid_token", "Invalid refresh token.")
    user = db.get(models.User, user_id)
    if user is None:
        return fail(401, "invalid_token", "User not found.")
    response = ok({"user": _user_public(user)})
    set_auth_cookies(response, user, request)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    response = ok({"message": "Signed out."})
    clear_auth_cookies(response, request)
    return response


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return ok({"user": _user_public(user)})


@router.post("/register")
def register(user: models.User = Depends(require_roles(*CAN_MANAGE_USERS))):
    return not_implemented("POST /auth/register")
