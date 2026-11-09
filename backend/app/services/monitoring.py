"""Monitoring service — v0.9.0.

Local-first, $0: metrics and alerts live in PostgreSQL
(request_metrics, alerts). No external service, no email, no
Telegram — the Admin sees everything on the Monitoring page.

Alert rules (LOCKED, thresholds from the Monitoring step):
    instruct_p95_latency   instruct p95 latency > 500 ms, last 1 h (min 5 samples)
    error_rate_5xx         5xx rate > 5% of requests, last 1 h (min 20 requests)
    eval_suite_fail        any scenario FAIL in the latest eval suite
    pending_approvals_backlog  pending approvals > 50
    scheduler_missed_fire  active job whose next_run_at passed > 5 min ago
                           (only checked while the scheduler is running)
    api_down               health endpoint unreachable (checked by
                           scripts/monitor_check.py, which passes
                           api_available=False)
    database_unavailable   a probe query against the database fails

check_alerts() is pure over a DB session: it fires new alerts, skips
duplicates (same rule already ACTIVE within 30 minutes), and
auto-resolves ACTIVE alerts whose condition has cleared. The
in-process scheduler calls it every 5 minutes when
MONITORING_ALERTS_ENABLED is true (production only by default).
"""
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging_config import data_dir
from app.db import models
from app.db.session import SessionLocal
from app.services import scheduler as scheduler_service

STARTED_AT = time.time()

RULES = {
    "instruct_p95_latency": {"severity": "MEDIUM", "threshold": "instruct p95 > 500 ms (last 1h, min 5 samples)"},
    "error_rate_5xx": {"severity": "HIGH", "threshold": "5xx rate > 5% (last 1h, min 20 requests)"},
    "eval_suite_fail": {"severity": "HIGH", "threshold": "any scenario FAIL in the latest eval suite"},
    "pending_approvals_backlog": {"severity": "MEDIUM", "threshold": "pending approvals > 50"},
    "scheduler_missed_fire": {"severity": "HIGH", "threshold": "active job next_run_at passed > 5 min ago"},
    "api_down": {"severity": "CRITICAL", "threshold": "health endpoint unreachable"},
    "database_unavailable": {"severity": "CRITICAL", "threshold": "database probe query fails"},
}

INSTRUCT_ENDPOINT = "/api/v1/agent/instruct"
DEDUP_MINUTES = 30
MISSED_FIRE_GRACE_MINUTES = 5


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile, rounded to 1 decimal. None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(pct / 100 * len(ordered))))
    return round(float(ordered[index]), 1)


def normalize_endpoint(path: str) -> str:
    """Collapse id-like path segments so /agent/runs/123/trace and
    /agent/runs/456/trace aggregate as one endpoint."""
    parts = []
    for segment in path.split("/"):
        if segment.isdigit() or re.fullmatch(r"[0-9a-f-]{8,}", segment or ""):
            parts.append("{id}")
        else:
            parts.append(segment)
    return "/".join(parts)


def record_request_metric(
    endpoint: str, method: str, status: int, latency_ms: int, role: str | None
) -> None:
    """Write one request row. Own session, fail-open: a metrics failure
    is logged and never propagates to the request being measured."""
    import logging

    db = SessionLocal()
    try:
        db.add(
            models.RequestMetric(
                endpoint=normalize_endpoint(endpoint),
                method=method,
                status=status,
                latency_ms=max(0, int(latency_ms)),
                role=role,
                created_at=_now(),
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - metrics must never break serving
        db.rollback()
        logging.getLogger(__name__).warning("Failed to record request metric.", exc_info=True)
    finally:
        db.close()


def _metrics_since(db: Session, since: datetime) -> list[models.RequestMetric]:
    return db.query(models.RequestMetric).filter(models.RequestMetric.created_at >= since).all()


def compute_summary(db: Session, hours: int = 24) -> dict:
    """Metrics summary: last `hours` hours plus all-time totals, plus
    agent metrics from workflow runs, approvals and evals. Every number
    comes from the database — nothing is seeded or estimated."""
    now = _now()
    since = now - timedelta(hours=hours)
    rows = _metrics_since(db, since)
    total_rows = db.query(func.count(models.RequestMetric.id)).scalar() or 0
    latencies = [r.latency_ms for r in rows]
    instruct_latencies = [r.latency_ms for r in rows if r.endpoint == INSTRUCT_ENDPOINT]
    errors_5xx = [r for r in rows if r.status >= 500]
    by_endpoint: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for r in rows:
        by_endpoint[r.endpoint] = by_endpoint.get(r.endpoint, 0) + 1
        by_status[str(r.status)] = by_status.get(str(r.status), 0) + 1
        by_role[r.role or "public"] = by_role.get(r.role or "public", 0) + 1

    runs = db.query(models.WorkflowRun).all()
    runs_by_status: dict[str, int] = {}
    confidences: list[float] = []
    for run in runs:
        runs_by_status[run.status] = runs_by_status.get(run.status, 0) + 1
        if run.confidence is not None:
            confidences.append(run.confidence)
    runs_24h = [r for r in runs if r.started_at and r.started_at >= since]
    approvals = db.query(models.Approval).all()
    approval_counts: dict[str, int] = {}
    for a in approvals:
        approval_counts[a.status] = approval_counts.get(a.status, 0) + 1
    latest_eval_at = db.query(func.max(models.EvalResult.run_at)).scalar()
    eval_total = eval_passed = 0
    if latest_eval_at is not None:
        latest = db.query(models.EvalResult).filter(models.EvalResult.run_at == latest_eval_at).all()
        eval_total = len(latest)
        eval_passed = sum(1 for r in latest if r.success)
    escalated = runs_by_status.get("ESCALATED", 0)
    completed = runs_by_status.get("COMPLETED", 0) + runs_by_status.get("AWAITING_APPROVAL", 0)
    return {
        "window_hours": hours,
        "generated_at": now.isoformat(),
        "requests_24h": len(rows),
        "requests_total": total_rows,
        "error_rate_5xx_24h": round(len(errors_5xx) / len(rows), 4) if rows else 0.0,
        "errors_5xx_24h": len(errors_5xx),
        "latency_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "samples": len(latencies),
        },
        "instruct_latency_ms": {
            "p50": percentile(instruct_latencies, 50),
            "p95": percentile(instruct_latencies, 95),
            "samples": len(instruct_latencies),
        },
        "by_endpoint": dict(sorted(by_endpoint.items(), key=lambda kv: -kv[1])[:15]),
        "by_status": by_status,
        "by_role": by_role,
        "runs_total": len(runs),
        "runs_24h": len(runs_24h),
        "runs_by_status": runs_by_status,
        "escalations_total": escalated,
        "confidence_avg": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "approvals": {
            "pending": approval_counts.get("PENDING", 0),
            "approved": approval_counts.get("APPROVED", 0),
            "rejected": approval_counts.get("REJECTED", 0),
        },
        "evals_latest": {
            "run_at": latest_eval_at.isoformat() if latest_eval_at else None,
            "total": eval_total,
            "passed": eval_passed,
            "failed": eval_total - eval_passed,
            "pass_rate": round(eval_passed / eval_total, 3) if eval_total else None,
        },
    }


def timeseries(db: Session, hours: int = 24) -> list[dict]:
    """Per-hour buckets (requests, 5xx, instruct count, p95) for the
    last `hours` hours. Buckets with no traffic are included as zeros
    so the chart has no gaps."""
    now = _now()
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    rows = db.query(models.RequestMetric).filter(models.RequestMetric.created_at >= start).all()
    buckets: dict[str, list[models.RequestMetric]] = {}
    cursor = start
    while cursor <= now:
        buckets[cursor.strftime("%Y-%m-%dT%H:00")] = []
        cursor += timedelta(hours=1)
    for r in rows:
        key = r.created_at.strftime("%Y-%m-%dT%H:00")
        if key in buckets:
            buckets[key].append(r)
    out = []
    for key in sorted(buckets):
        bucket = buckets[key]
        out.append(
            {
                "hour": key,
                "requests": len(bucket),
                "errors_5xx": sum(1 for r in bucket if r.status >= 500),
                "instruct": sum(1 for r in bucket if r.endpoint == INSTRUCT_ENDPOINT),
                "p95_ms": percentile([r.latency_ms for r in bucket], 95),
            }
        )
    return out


def _fire(db: Session, rule: str, message: str, details: dict, now: datetime) -> models.Alert | None:
    """Create an ACTIVE alert unless the same rule already has one
    created within the dedup window. Returns the new alert or None."""
    since = now - timedelta(minutes=DEDUP_MINUTES)
    existing = (
        db.query(models.Alert)
        .filter(models.Alert.rule == rule, models.Alert.status == "ACTIVE", models.Alert.created_at >= since)
        .first()
    )
    if existing is not None:
        return None
    alert = models.Alert(
        rule=rule,
        severity=RULES[rule]["severity"],
        message=message,
        status="ACTIVE",
        details=details,
        created_at=now,
    )
    db.add(alert)
    db.commit()
    return alert


def _clear(db: Session, rule: str, now: datetime) -> int:
    """Auto-resolve ACTIVE alerts for a rule whose condition cleared."""
    active = db.query(models.Alert).filter(models.Alert.rule == rule, models.Alert.status == "ACTIVE").all()
    for alert in active:
        alert.status = "RESOLVED"
        alert.resolved_at = now
    if active:
        db.commit()
    return len(active)


def _latest_eval_failures(db: Session) -> list[models.EvalResult]:
    latest_at = db.query(func.max(models.EvalResult.run_at)).scalar()
    if latest_at is None:
        return []
    return (
        db.query(models.EvalResult)
        .filter(models.EvalResult.run_at == latest_at, models.EvalResult.success.is_(False))
        .all()
    )


def _missed_jobs(db: Session, now: datetime) -> list[models.ScheduledJob]:
    """Active jobs whose next run passed more than the grace period
    ago. A job that fired advances its own next_run_at, so a stale
    past value means the fire was missed."""
    cutoff = now - timedelta(minutes=MISSED_FIRE_GRACE_MINUTES)
    return (
        db.query(models.ScheduledJob)
        .filter(
            models.ScheduledJob.is_active.is_(True),
            models.ScheduledJob.next_run_at.isnot(None),
            models.ScheduledJob.next_run_at < cutoff,
        )
        .all()
    )


def check_alerts(
    db: Session,
    *,
    api_available: bool = True,
    now: datetime | None = None,
) -> dict:
    """Evaluate all six rules against the live database and the API
    health passed in by the caller. Returns fired / cleared / skipped
    (dedup) rule names. Never raises — a failed rule is logged and
    reported, not fatal to the other rules."""
    import logging

    logger = logging.getLogger(__name__)
    now = now or _now()
    fired: list[str] = []
    cleared: list[str] = []
    skipped: list[str] = []
    hour_ago = now - timedelta(hours=1)

    # (f) Database availability — a probe query first; without the
    # database no other rule can be evaluated honestly.
    db_available = True
    try:
        db.execute(func.now()).scalar()
    except Exception:  # noqa: BLE001 - the probe failing IS the signal
        db.rollback()
        db_available = False
    if not db_available:
        alert = _fire(
            db, "database_unavailable", "Database probe query failed — PostgreSQL is unreachable.",
            {}, now,
        )
        (fired if alert else skipped).append("database_unavailable")
        return {"fired": fired, "cleared": cleared, "skipped": skipped, "db_available": False}
    _clear(db, "database_unavailable", now) and cleared.append("database_unavailable")

    # (f) API availability.
    if not api_available:
        alert = _fire(db, "api_down", "Health endpoint unreachable — the API is down.", {}, now)
        (fired if alert else skipped).append("api_down")
    else:
        _clear(db, "api_down", now) and cleared.append("api_down")

    # (a) Instruct p95 latency.
    try:
        instruct = [
            r.latency_ms
            for r in db.query(models.RequestMetric)
            .filter(
                models.RequestMetric.endpoint == INSTRUCT_ENDPOINT,
                models.RequestMetric.created_at >= hour_ago,
            )
            .all()
        ]
        p95 = percentile(instruct, 95)
        if p95 is not None and len(instruct) >= 5 and p95 > 500:
            alert = _fire(
                db, "instruct_p95_latency",
                f"Instruct p95 latency {p95} ms over the last hour ({len(instruct)} samples) exceeds 500 ms.",
                {"p95_ms": p95, "samples": len(instruct)}, now,
            )
            (fired if alert else skipped).append("instruct_p95_latency")
        else:
            _clear(db, "instruct_p95_latency", now) and cleared.append("instruct_p95_latency")
    except Exception:  # noqa: BLE001 - one rule failing must not stop the rest
        db.rollback()
        logger.exception("Alert rule instruct_p95_latency failed.")

    # (b) 5xx error rate.
    try:
        hour_rows = db.query(models.RequestMetric).filter(models.RequestMetric.created_at >= hour_ago).all()
        total = len(hour_rows)
        errors = sum(1 for r in hour_rows if r.status >= 500)
        rate = errors / total if total else 0.0
        if total >= 20 and rate > 0.05:
            alert = _fire(
                db, "error_rate_5xx",
                f"5xx error rate {rate:.1%} ({errors}/{total} requests) over the last hour exceeds 5%.",
                {"rate": round(rate, 4), "errors": errors, "total": total}, now,
            )
            (fired if alert else skipped).append("error_rate_5xx")
        else:
            _clear(db, "error_rate_5xx", now) and cleared.append("error_rate_5xx")
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Alert rule error_rate_5xx failed.")

    # (c) Eval suite failure.
    try:
        failures = _latest_eval_failures(db)
        if failures:
            names = [f.scenario for f in failures]
            alert = _fire(
                db, "eval_suite_fail",
                f"Latest eval suite has {len(failures)} failed scenario(s): {', '.join(names[:5])}.",
                {"failed_scenarios": names}, now,
            )
            (fired if alert else skipped).append("eval_suite_fail")
        else:
            _clear(db, "eval_suite_fail", now) and cleared.append("eval_suite_fail")
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Alert rule eval_suite_fail failed.")

    # (d) Pending approvals backlog.
    try:
        pending = (
            db.query(func.count(models.Approval.id))
            .filter(models.Approval.status == "PENDING")
            .scalar()
            or 0
        )
        if pending > 50:
            alert = _fire(
                db, "pending_approvals_backlog",
                f"Pending approvals backlog is {pending} (threshold 50) — managers need to work through the queue.",
                {"pending": pending}, now,
            )
            (fired if alert else skipped).append("pending_approvals_backlog")
        else:
            _clear(db, "pending_approvals_backlog", now) and cleared.append("pending_approvals_backlog")
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Alert rule pending_approvals_backlog failed.")

    # (e) Scheduler missed fire — only meaningful while the scheduler
    # is actually running; otherwise next_run_at goes stale by design.
    try:
        if scheduler_service.is_scheduler_running():
            missed = _missed_jobs(db, now)
            if missed:
                labels = [f"job #{j.id} (next run was {j.next_run_at})" for j in missed]
                alert = _fire(
                    db, "scheduler_missed_fire",
                    f"Scheduler missed {len(missed)} fire(s): {'; '.join(labels)}.",
                    {"job_ids": [j.id for j in missed]}, now,
                )
                (fired if alert else skipped).append("scheduler_missed_fire")
            else:
                _clear(db, "scheduler_missed_fire", now) and cleared.append("scheduler_missed_fire")
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Alert rule scheduler_missed_fire failed.")

    return {"fired": fired, "cleared": cleared, "skipped": skipped, "db_available": True}


def run_monitoring_check(api_url: str | None = None) -> dict:
    """One alert-check pass (used by the 5-minute scheduler job and by
    scripts/monitor_check.py). Probes the health endpoint, then
    evaluates the rules. Never raises."""
    import logging

    import httpx

    logger = logging.getLogger(__name__)
    api_available = True
    if api_url:
        try:
            response = httpx.get(f"{api_url.rstrip('/')}/api/v1/health", timeout=10, trust_env=False)
            api_available = response.status_code == 200 and response.json().get("success") is True
        except Exception:  # noqa: BLE001 - unreachable API is the signal
            api_available = False
    db = SessionLocal()
    try:
        result = check_alerts(db, api_available=api_available)
        for rule in result["fired"]:
            logger.warning("Monitoring alert fired: %s", rule)
        return result
    except Exception:  # noqa: BLE001 - the checker must never crash the scheduler
        logger.exception("Monitoring check failed.")
        return {"fired": [], "cleared": [], "skipped": [], "db_available": False}
    finally:
        db.close()


def disk_usage() -> dict:
    """Disk usage of the data directory's filesystem, plus its size."""
    root = data_dir()
    total = used = free = 0
    try:
        usage = shutil.disk_usage(root)
        total, used, free = usage.total, usage.used, usage.free
    except OSError:
        pass
    size_bytes = 0
    try:
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    size_bytes += path.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return {
        "path": str(root),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_percent": round(used / total * 100, 1) if total else None,
        "data_dir_bytes": size_bytes,
    }


def monitoring_overview(db: Session) -> dict:
    """Everything the Monitoring page needs in one call: health,
    summary, scheduler state, disk, alert counts and newest 5xx.
    The database state is probed live (not taken from the startup
    global, which a test client without lifespan never sets)."""
    try:
        db.execute(func.now()).scalar()
        db_status = "connected"
    except Exception as exc:  # noqa: BLE001 - the probe failing IS the status
        db.rollback()
        db_status = f"unavailable: {exc}"
    summary = compute_summary(db)
    active_alerts = (
        db.query(models.Alert).filter(models.Alert.status == "ACTIVE").order_by(models.Alert.id.desc()).all()
    )
    recent_errors = (
        db.query(models.RequestMetric)
        .filter(models.RequestMetric.status >= 500)
        .order_by(models.RequestMetric.id.desc())
        .limit(5)
        .all()
    )
    return {
        "version": settings.version,
        "environment": settings.environment,
        "service": settings.service,
        "database": db_status,
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
        "scheduler_running": scheduler_service.is_scheduler_running(),
        "monitoring_alerts_enabled": settings.monitoring_alerts_enabled,
        "summary": summary,
        "active_alerts": [
            {
                "id": a.id,
                "rule": a.rule,
                "severity": a.severity,
                "message": a.message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in active_alerts
        ],
        "active_alert_count": len(active_alerts),
        "recent_errors": [
            {
                "endpoint": e.endpoint,
                "method": e.method,
                "status": e.status,
                "latency_ms": e.latency_ms,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in recent_errors
        ],
        "disk": disk_usage(),
    }
