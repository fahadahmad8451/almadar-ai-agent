"""Admin endpoints — Sprint 3, LIVE.

User management and the audit log (Admin only unless noted):
- GET /admin/users — list users (Admin).
- PUT /admin/users/{email}/role — change a role (Admin). An admin
  cannot change their own role.
- POST /admin/users/{email}/reset-password — Admin sets a new
  password and receives it in the response to pass to the user
  out-of-band. There is no email in this project, so no fake email
  is sent (same honest pattern as Project 1 v0.10).
- GET /admin/audit (alias: /admin/audit-logs) — filterable audit log
  (Admin + Operations Manager).
- GET /admin/observability — run stats, latency percentiles, token
  totals, approval queue age (Admin + Operations Manager).
Every admin action writes an audit row.
"""
import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1._helpers import fail, ok
from app.core.security import (
    ALL_ROLES,
    CAN_MANAGE_USERS,
    CAN_VIEW_AUDIT,
    PWD,
    audit,
    get_current_user,
    require_roles,
)
from app.db import models
from app.db.session import get_db
from app.services import monitoring as monitoring_service

router = APIRouter()


def _user_public(u: models.User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RoleBody(BaseModel):
    role: str = Field(min_length=1)


@router.get("/users")
def list_users(
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    users = db.query(models.User).order_by(models.User.id).all()
    return ok({"users": [_user_public(u) for u in users], "count": len(users)})


@router.put("/users/{email}/role")
def change_user_role(
    email: str,
    body: RoleBody,
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    if body.role not in ALL_ROLES:
        return fail(
            400,
            "invalid_role",
            f"Unknown role: {body.role!r}. Use one of {', '.join(ALL_ROLES)}.",
        )
    target = db.query(models.User).filter(models.User.email == email.lower()).first()
    if target is None:
        return fail(404, "not_found", "User not found.")
    if target.id == user.id:
        return fail(403, "forbidden", "You cannot change your own role.")
    old_role = target.role
    target.role = body.role
    db.commit()
    audit(
        db,
        user_id=user.id,
        action="ROLE_CHANGE",
        resource=f"admin/users/{target.email}/role",
        result="SUCCESS",
        details={"old_role": old_role, "new_role": body.role},
    )
    return ok({"user": _user_public(target), "old_role": old_role})


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in password) and any(c.isalpha() for c in password):
            return password


@router.post("/users/{email}/reset-password")
def reset_user_password(
    email: str,
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.email == email.lower()).first()
    if target is None:
        return fail(404, "not_found", "User not found.")
    new_password = _generate_password()
    target.password_hash = PWD.hash(new_password)
    db.commit()
    audit(
        db,
        user_id=user.id,
        action="PASSWORD_RESET",
        resource=f"admin/users/{target.email}/reset-password",
        result="SUCCESS",
        details={},
    )
    return ok(
        {
            "email": target.email,
            "new_password": new_password,
            "note": (
                "No email is sent — there is no mail server in this project. "
                "Share this password with the user out-of-band; they should "
                "change it after signing in."
            ),
        }
    )


def _audit_public(row: models.AuditLog) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "action": row.action,
        "resource": row.resource,
        "result": row.result,
        "details": row.details,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/audit")
def list_audit(
    action: str | None = Query(default=None),
    result: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: models.User = Depends(require_roles(*CAN_VIEW_AUDIT)),
    db: Session = Depends(get_db),
):
    query = db.query(models.AuditLog).order_by(models.AuditLog.id.desc())
    if action:
        query = query.filter(models.AuditLog.action == action.upper())
    if result:
        query = query.filter(models.AuditLog.result == result.upper())
    if user_id is not None:
        query = query.filter(models.AuditLog.user_id == user_id)
    rows = query.limit(limit).all()
    return ok({"audit_logs": [_audit_public(r) for r in rows], "count": len(rows)})


@router.get("/audit-logs")
def list_audit_logs_alias(
    action: str | None = Query(default=None),
    result: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: models.User = Depends(require_roles(*CAN_VIEW_AUDIT)),
    db: Session = Depends(get_db),
):
    """Alias of GET /admin/audit (the Design section 6 name)."""
    return list_audit(action=action, result=result, user_id=user_id, limit=limit, user=user, db=db)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(pct / 100 * len(ordered))))
    return round(float(ordered[index]), 1)


# --- Monitoring (v0.9.0) — Admin only -------------------------------------
# Metrics and alerts are real database rows (request_metrics, alerts);
# nothing here is seeded, estimated or mocked. See docs/MONITORING.md.

def _alert_public(row: models.Alert) -> dict:
    return {
        "id": row.id,
        "rule": row.rule,
        "severity": row.severity,
        "message": row.message,
        "status": row.status,
        "details": row.details,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolved_by": row.resolved_by,
    }


@router.get("/metrics/summary")
def metrics_summary(
    hours: int = Query(default=24, ge=1, le=168),
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    return ok(monitoring_service.compute_summary(db, hours=hours))


@router.get("/metrics/timeseries")
def metrics_timeseries(
    hours: int = Query(default=24, ge=1, le=168),
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    return ok({"hours": hours, "buckets": monitoring_service.timeseries(db, hours=hours)})


@router.get("/alerts")
def list_alerts(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    query = db.query(models.Alert).order_by(models.Alert.id.desc())
    if status:
        query = query.filter(models.Alert.status == status.upper())
    rows = query.limit(limit).all()
    return ok({"alerts": [_alert_public(r) for r in rows], "count": len(rows)})


class ResolveBody(BaseModel):
    comment: str | None = Field(default=None)


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: int,
    body: ResolveBody | None = None,
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    alert = db.get(models.Alert, alert_id)
    if alert is None:
        return fail(404, "not_found", "Alert not found.")
    if alert.status == "RESOLVED":
        return ok({"alert": _alert_public(alert), "note": "Alert was already resolved."})
    alert.status = "RESOLVED"
    alert.resolved_at = _now()
    alert.resolved_by = user.id
    db.commit()
    audit(
        db,
        user_id=user.id,
        action="ALERT_RESOLVE",
        resource=f"admin/alerts/{alert.id}/resolve",
        result="SUCCESS",
        details={"rule": alert.rule, "comment": (body.comment if body else None)},
    )
    return ok({"alert": _alert_public(alert)})


@router.get("/monitoring/overview")
def monitoring_overview(
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    return ok(monitoring_service.monitoring_overview(db))


@router.get("/monitoring/recent-errors")
def monitoring_recent_errors(
    limit: int = Query(default=20, ge=1, le=100),
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.RequestMetric)
        .filter(models.RequestMetric.status >= 500)
        .order_by(models.RequestMetric.id.desc())
        .limit(limit)
        .all()
    )
    return ok(
        {
            "errors": [
                {
                    "id": r.id,
                    "endpoint": r.endpoint,
                    "method": r.method,
                    "status": r.status,
                    "latency_ms": r.latency_ms,
                    "role": r.role,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
            "count": len(rows),
        }
    )


@router.get("/monitoring/daily-reports")
def monitoring_daily_reports(
    user: models.User = Depends(require_roles(*CAN_MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    """Daily reports written by scripts/daily_report.py into
    <data-dir>/reports/ (JSON + Markdown). Returns the list, newest
    first, with the newest report's Markdown included."""
    from app.core.logging_config import reports_dir

    directory = reports_dir()
    reports = []
    if directory.is_dir():
        for path in sorted(directory.glob("daily-*.md"), reverse=True):
            json_path = path.with_suffix(".json")
            reports.append(
                {
                    "name": path.name,
                    "date": path.name[len("daily-") : -len(".md")],
                    "size_bytes": path.stat().st_size,
                    "has_json": json_path.is_file(),
                }
            )
    latest_markdown = None
    if reports:
        latest_path = directory / reports[0]["name"]
        try:
            latest_markdown = latest_path.read_text(encoding="utf-8")
        except OSError:
            latest_markdown = None
    return ok({"reports": reports, "count": len(reports), "latest_markdown": latest_markdown})


@router.get("/observability")
def observability(
    user: models.User = Depends(require_roles(*CAN_VIEW_AUDIT)),
    db: Session = Depends(get_db),
):
    runs = db.query(models.WorkflowRun).all()
    by_status: dict[str, int] = {}
    for run in runs:
        by_status[run.status] = by_status.get(run.status, 0) + 1
    latencies = [
        row[0]
        for row in db.query(models.WorkflowStep.latency_ms)
        .filter(models.WorkflowStep.latency_ms.isnot(None))
        .all()
    ]
    tokens = db.query(models.WorkflowStep.tokens).filter(
        models.WorkflowStep.tokens.isnot(None)
    ).all()
    token_total = sum(v[0] for v in tokens if v[0] is not None)
    pending = (
        db.query(models.Approval)
        .filter(models.Approval.status == "PENDING")
        .order_by(models.Approval.id)
        .all()
    )
    oldest_pending_age_hours = None
    if pending:
        oldest = db.query(models.WorkflowRun).get(pending[0].run_id)
        if oldest is not None:
            oldest_pending_age_hours = round(
                (_now() - oldest.started_at).total_seconds() / 3600, 2
            )
    total = len(runs)
    completed = by_status.get("COMPLETED", 0) + by_status.get("AWAITING_APPROVAL", 0)
    return ok(
        {
            "runs_total": total,
            "runs_by_status": by_status,
            "success_rate": round(completed / total, 3) if total else None,
            "latency_ms": {
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
                "samples": len(latencies),
            },
            "tokens_total": token_total,
            "pending_approvals": len(pending),
            "oldest_pending_approval_age_hours": oldest_pending_age_hours,
        }
    )
