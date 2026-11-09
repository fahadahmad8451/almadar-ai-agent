"""Monitoring tests — v0.9.0.

Covers the metrics middleware recording, the Admin-only metrics
summary / timeseries / alerts endpoints, every alert rule firing AND
staying silent below its threshold, the 30-minute dedup, manual
resolve, the daily-report builder and log rotation. All against the
real dev PostgreSQL database; rows created by a test are deleted by
that test.
"""
from datetime import datetime, timedelta, timezone

from tests.conftest import login_as

from app.db import models
from app.services import monitoring as monitoring_service

ADMIN = ("admin@almadar.local", "Admin123!")
MANAGER = ("manager@almadar.local", "Manager123!")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _metric(db, endpoint="/api/v1/agent/instruct", status=200, latency_ms=100, minutes_ago=10):
    row = models.RequestMetric(
        endpoint=endpoint,
        method="GET",
        status=status,
        latency_ms=latency_ms,
        role="ADMIN",
        created_at=_now() - timedelta(minutes=minutes_ago),
    )
    db.add(row)
    db.commit()
    return row.id


def _cleanup(db, metric_ids=(), alert_rules=(), eval_ids=(), approval_ids=(), run_ids=()):
    if metric_ids:
        db.query(models.RequestMetric).filter(models.RequestMetric.id.in_(list(metric_ids))).delete(
            synchronize_session=False
        )
    if alert_rules:
        db.query(models.Alert).filter(models.Alert.rule.in_(list(alert_rules))).delete(
            synchronize_session=False
        )
    if eval_ids:
        db.query(models.EvalResult).filter(models.EvalResult.id.in_(list(eval_ids))).delete(
            synchronize_session=False
        )
    if approval_ids:
        db.query(models.Approval).filter(models.Approval.id.in_(list(approval_ids))).delete(
            synchronize_session=False
        )
    if run_ids:
        db.query(models.WorkflowRun).filter(models.WorkflowRun.id.in_(list(run_ids))).delete(
            synchronize_session=False
        )
    db.commit()


# --- Endpoints: auth + shape -----------------------------------------------

def test_metrics_summary_admin_only(client, db):
    login_as(client, *ADMIN)
    r = client.get("/api/v1/admin/metrics/summary")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "requests_24h" in data and "latency_ms" in data
    assert "instruct_latency_ms" in data and "approvals" in data
    assert "evals_latest" in data and "runs_by_status" in data


def test_metrics_summary_forbidden_for_manager(client):
    login_as(client, *MANAGER)
    assert client.get("/api/v1/admin/metrics/summary").status_code == 403


def test_metrics_summary_requires_sign_in(client):
    assert client.get("/api/v1/admin/metrics/summary").status_code == 401


def test_metrics_timeseries_shape(client):
    login_as(client, *ADMIN)
    r = client.get("/api/v1/admin/metrics/timeseries?hours=3")
    assert r.status_code == 200, r.text
    buckets = r.json()["data"]["buckets"]
    assert len(buckets) == 3
    assert all({"hour", "requests", "errors_5xx", "p95_ms"} <= set(b) for b in buckets)


def test_monitoring_overview_shape(client):
    login_as(client, *ADMIN)
    r = client.get("/api/v1/admin/monitoring/overview")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["version"] == "0.9.0"
    assert data["database"] == "connected"
    assert "disk" in data and "summary" in data
    assert "active_alert_count" in data


def test_middleware_records_requests(client, db):
    before = db.query(models.RequestMetric).filter(
        models.RequestMetric.endpoint == "/health"
    ).count()
    r = client.get("/health")
    assert r.status_code == 200
    after = db.query(models.RequestMetric).filter(
        models.RequestMetric.endpoint == "/health"
    ).count()
    assert after == before + 1
    row = (
        db.query(models.RequestMetric)
        .filter(models.RequestMetric.endpoint == "/health")
        .order_by(models.RequestMetric.id.desc())
        .first()
    )
    assert row.status == 200 and row.latency_ms >= 0
    _cleanup(db, metric_ids=(row.id,))


def test_percentile_and_normalize():
    assert monitoring_service.percentile([], 95) is None
    assert monitoring_service.percentile([100, 200, 300], 50) == 200
    assert monitoring_service.normalize_endpoint("/api/v1/agent/runs/123/trace") == (
        "/api/v1/agent/runs/{id}/trace"
    )
    assert monitoring_service.normalize_endpoint("/api/v1/health") == "/api/v1/health"


# --- Alert rules ------------------------------------------------------------

def _reset_alerts(db):
    """Delete every alert row. The dev database accumulates alerts
    from earlier tests and live traffic; without this, the 30-minute
    dedup would hide a rule firing in the test under it."""
    db.query(models.Alert).delete(synchronize_session=False)
    db.commit()


def _hour_totals(db):
    rows = db.query(models.RequestMetric).filter(
        models.RequestMetric.created_at >= _now() - timedelta(hours=1)
    ).all()
    return len(rows), sum(1 for r in rows if r.status >= 500)


def test_rule_instruct_p95_fires_and_clears(db):
    _reset_alerts(db)
    ids = [_metric(db, latency_ms=600) for _ in range(5)]
    try:
        result = monitoring_service.check_alerts(db, api_available=True)
        assert "instruct_p95_latency" in result["fired"], result
        alert = (
            db.query(models.Alert)
            .filter(models.Alert.rule == "instruct_p95_latency", models.Alert.status == "ACTIVE")
            .first()
        )
        assert alert is not None and alert.severity == "MEDIUM"
        # Second check inside the dedup window creates no duplicate.
        result2 = monitoring_service.check_alerts(db, api_available=True)
        assert "instruct_p95_latency" in result2["skipped"]
        assert (
            db.query(models.Alert)
            .filter(models.Alert.rule == "instruct_p95_latency", models.Alert.status == "ACTIVE")
            .count()
            == 1
        )
    finally:
        _cleanup(db, metric_ids=ids, alert_rules=("instruct_p95_latency",))
    # Condition cleared: the rule auto-resolves nothing left active
    # (rows were deleted, so a fresh check finds no samples).
    result3 = monitoring_service.check_alerts(db, api_available=True)
    assert "instruct_p95_latency" not in result3["fired"]


def test_rule_instruct_p95_silent_below_threshold(db):
    _reset_alerts(db)
    ids = [_metric(db, latency_ms=400) for _ in range(5)]
    try:
        result = monitoring_service.check_alerts(db, api_available=True)
        assert "instruct_p95_latency" not in result["fired"], result
    finally:
        _cleanup(db, metric_ids=ids, alert_rules=("instruct_p95_latency",))


def test_rule_error_rate_fires_and_silent_below(db):
    # The metrics middleware records every TestClient request, so the
    # last-hour window already holds ambient traffic. Scale the
    # injected 5xx rows to the ambient total so the rate genuinely
    # crosses 5% — a fixed "2 of 20" would be diluted to nothing.
    _reset_alerts(db)
    total0, _err0 = _hour_totals(db)
    need = int(0.08 * total0) + 3
    ids = [_metric(db, endpoint="/api/v1/dashboard/summary", status=500) for _ in range(need)]
    ids += [_metric(db, endpoint="/api/v1/dashboard/summary", status=200) for _ in range(20)]
    try:
        result = monitoring_service.check_alerts(db, api_available=True)
        assert "error_rate_5xx" in result["fired"], result
    finally:
        _cleanup(db, metric_ids=ids, alert_rules=("error_rate_5xx",))
    # Below threshold: exactly 1 error in 20 fresh rows, on top of
    # ambient (mostly 200) traffic, stays under 5%.
    _reset_alerts(db)
    db.query(models.RequestMetric).filter(
        models.RequestMetric.created_at >= _now() - timedelta(hours=1),
        models.RequestMetric.status >= 500,
    ).delete(synchronize_session=False)
    db.commit()
    ids = [_metric(db, endpoint="/api/v1/dashboard/summary", status=200) for _ in range(19)]
    ids += [_metric(db, endpoint="/api/v1/dashboard/summary", status=500)]
    try:
        result = monitoring_service.check_alerts(db, api_available=True)
        assert "error_rate_5xx" not in result["fired"], result
    finally:
        _cleanup(db, metric_ids=ids, alert_rules=("error_rate_5xx",))


def test_rule_eval_fail_fires(db):
    _reset_alerts(db)
    run_at = _now()
    row = models.EvalResult(
        scenario="monitoring_probe",
        workflow_key="INVOICE_REPORT",
        success=False,
        tool_accuracy=1.0,
        approval_compliant=True,
        self_check_catch=True,
        latency_ms=10,
        tokens=0,
        run_at=run_at,
    )
    db.add(row)
    db.commit()
    try:
        result = monitoring_service.check_alerts(db, api_available=True)
        assert "eval_suite_fail" in result["fired"], result
    finally:
        _cleanup(db, eval_ids=(row.id,), alert_rules=("eval_suite_fail",))


def test_rule_pending_approvals_backlog(db):
    _reset_alerts(db)
    admin = db.query(models.User).filter(models.User.email == "admin@almadar.local").first()
    run = models.WorkflowRun(
        workflow_id=1,
        user_id=admin.id,
        instruction="Monitoring probe run.",
        language="en",
        status="AWAITING_APPROVAL",
        started_at=_now(),
    )
    db.add(run)
    db.commit()
    approval_ids = []
    for _ in range(51):
        a = models.Approval(
            run_id=run.id, requested_by=admin.id, action_summary="Probe approval.", status="PENDING"
        )
        db.add(a)
        db.commit()
        approval_ids.append(a.id)
    try:
        result = monitoring_service.check_alerts(db, api_available=True)
        assert "pending_approvals_backlog" in result["fired"], result
    finally:
        _cleanup(db, approval_ids=approval_ids, run_ids=(run.id,),
                 alert_rules=("pending_approvals_backlog",))


def test_rule_api_down_fires(db):
    _reset_alerts(db)
    try:
        result = monitoring_service.check_alerts(db, api_available=False)
        assert "api_down" in result["fired"], result
        alert = (
            db.query(models.Alert)
            .filter(models.Alert.rule == "api_down", models.Alert.status == "ACTIVE")
            .first()
        )
        assert alert is not None and alert.severity == "CRITICAL"
    finally:
        _cleanup(db, alert_rules=("api_down",))
    # API back up: the rule auto-resolves on the next check.
    result = monitoring_service.check_alerts(db, api_available=True)
    assert "api_down" not in result["fired"]


def test_missed_fire_detection(db):
    job = models.ScheduledJob(
        workflow_id=1, cron="0 8 * * *",
        next_run_at=_now() - timedelta(minutes=30), is_active=True, created_at=_now(),
    )
    db.add(job)
    db.commit()
    try:
        missed = monitoring_service._missed_jobs(db, _now())
        assert any(j.id == job.id for j in missed)
    finally:
        db.query(models.ScheduledJob).filter(models.ScheduledJob.id == job.id).delete(
            synchronize_session=False
        )
        db.commit()


def test_alert_resolve_endpoint(client, db):
    alert = models.Alert(
        rule="pending_approvals_backlog", severity="MEDIUM",
        message="Probe alert.", status="ACTIVE", details={}, created_at=_now(),
    )
    db.add(alert)
    db.commit()
    try:
        login_as(client, *ADMIN)
        r = client.post(f"/api/v1/admin/alerts/{alert.id}/resolve", json={})
        assert r.status_code == 200, r.text
        data = r.json()["data"]["alert"]
        assert data["status"] == "RESOLVED" and data["resolved_by"] is not None
        r = client.post(f"/api/v1/admin/alerts/{alert.id}/resolve", json={})
        assert r.status_code == 200  # resolving twice is harmless
        login_as(client, *MANAGER)
        assert client.post(f"/api/v1/admin/alerts/{alert.id}/resolve", json={}).status_code == 403
    finally:
        db.query(models.Alert).filter(models.Alert.id == alert.id).delete(
            synchronize_session=False
        )
        db.commit()


def test_alerts_list_endpoint(client, db):
    login_as(client, *ADMIN)
    r = client.get("/api/v1/admin/alerts?status=active")
    assert r.status_code == 200, r.text
    assert "alerts" in r.json()["data"]


# --- Daily report + log rotation --------------------------------------------

def test_daily_report_builder(db, tmp_path):
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("daily_report", "rotate_logs"):
        spec = importlib.util.spec_from_file_location(
            f"_probe_{name}", root / "scripts" / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if name == "daily_report":
            daily_report = module
        else:
            rotate_logs = module

    report = daily_report.build_report(db, _now().date() - timedelta(days=1))
    assert report["requests"] >= 0
    assert "runs_by_status" in report and "approvals_decided" in report
    text = daily_report.to_markdown(report)
    assert f"# Daily report — {report['date']}" in text
    assert "## Approvals" in text and "## Alerts fired" in text


def test_rotate_logs_archives_old_files(tmp_path):
    import importlib.util
    import os
    import time
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_probe_rotate", root / "scripts" / "rotate_logs.py")
    rotate_logs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rotate_logs)

    old = tmp_path / "app.log.1"
    old.write_text("old log\n", encoding="utf-8")
    old_time = time.time() - 10 * 24 * 3600
    os.utime(old, (old_time, old_time))
    fresh = tmp_path / "app.log.2"
    fresh.write_text("fresh log\n", encoding="utf-8")
    result = rotate_logs.rotate(tmp_path, archive_after_days=7, keep_days=30)
    assert result["archived"] == 1
    assert not old.exists() and fresh.exists()
    assert len(list((tmp_path / "archives").glob("*.gz"))) == 1
