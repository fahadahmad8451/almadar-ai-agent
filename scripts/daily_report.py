"""Daily monitoring report — v0.9.0.

Builds yesterday's (or --date's) summary from the real database —
requests, runs, approvals approve/reject, errors, latency, evals and
alerts — and writes it to <data-dir>/reports/daily-YYYY-MM-DD.json
and daily-YYYY-MM-DD.md. Counts only, no instruction text, no PII.
No email is sent (there is no SMTP); the report is a file, and the
Monitoring page shows the newest one.

Usage:
    AMH_ENV_FILE=.env.production python scripts/daily_report.py [--date YYYY-MM-DD]
    AMH_ENV_FILE=.env.staging    python scripts/daily_report.py
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.logging_config import reports_dir  # noqa: E402
from app.db import models  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services import monitoring as monitoring_service  # noqa: E402


def build_report(db, day: date) -> dict:
    """Summary for one calendar day (UTC). All numbers from the DB."""
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    rows = (
        db.query(models.RequestMetric)
        .filter(models.RequestMetric.created_at >= start, models.RequestMetric.created_at < end)
        .all()
    )
    errors = [r for r in rows if r.status >= 500]
    by_endpoint: dict[str, int] = {}
    for r in rows:
        by_endpoint[r.endpoint] = by_endpoint.get(r.endpoint, 0) + 1
    runs = (
        db.query(models.WorkflowRun)
        .filter(models.WorkflowRun.started_at >= start, models.WorkflowRun.started_at < end)
        .all()
    )
    runs_by_status: dict[str, int] = {}
    for run in runs:
        runs_by_status[run.status] = runs_by_status.get(run.status, 0) + 1
    approvals = (
        db.query(models.Approval)
        .filter(models.Approval.decided_at >= start, models.Approval.decided_at < end)
        .all()
    )
    decided = {"APPROVED": 0, "REJECTED": 0}
    for a in approvals:
        if a.status in decided:
            decided[a.status] += 1
    evals = (
        db.query(models.EvalResult)
        .filter(models.EvalResult.run_at >= start, models.EvalResult.run_at < end)
        .all()
    )
    alerts = (
        db.query(models.Alert)
        .filter(models.Alert.created_at >= start, models.Alert.created_at < end)
        .all()
    )
    return {
        "date": day.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requests": len(rows),
        "errors_5xx": len(errors),
        "error_rate_5xx": round(len(errors) / len(rows), 4) if rows else 0.0,
        "latency_ms": {
            "p50": monitoring_service.percentile([r.latency_ms for r in rows], 50),
            "p95": monitoring_service.percentile([r.latency_ms for r in rows], 95),
        },
        "instruct_latency_ms": {
            "p50": monitoring_service.percentile(
                [r.latency_ms for r in rows if r.endpoint == monitoring_service.INSTRUCT_ENDPOINT], 50
            ),
            "p95": monitoring_service.percentile(
                [r.latency_ms for r in rows if r.endpoint == monitoring_service.INSTRUCT_ENDPOINT], 95
            ),
        },
        "top_endpoints": dict(sorted(by_endpoint.items(), key=lambda kv: -kv[1])[:10]),
        "runs": len(runs),
        "runs_by_status": runs_by_status,
        "approvals_decided": decided,
        "approvals_pending_now": db.query(models.Approval)
        .filter(models.Approval.status == "PENDING")
        .count(),
        "evals": {
            "total": len(evals),
            "passed": sum(1 for e in evals if e.success),
            "failed": sum(1 for e in evals if not e.success),
        },
        "alerts_fired": [
            {"rule": a.rule, "severity": a.severity, "message": a.message, "status": a.status}
            for a in alerts
        ],
    }


def to_markdown(report: dict) -> str:
    lines = [
        f"# Daily report — {report['date']}",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Requests",
        "",
        f"- Total requests: {report['requests']}",
        f"- 5xx errors: {report['errors_5xx']} ({report['error_rate_5xx']:.2%})",
        f"- Latency p50: {report['latency_ms']['p50']} ms, p95: {report['latency_ms']['p95']} ms",
        f"- Instruct latency p50: {report['instruct_latency_ms']['p50']} ms, "
        f"p95: {report['instruct_latency_ms']['p95']} ms",
        "",
        "## Top endpoints",
        "",
    ]
    for endpoint, count in report["top_endpoints"].items():
        lines.append(f"- {endpoint}: {count}")
    lines += [
        "",
        "## Agent runs",
        "",
        f"- Runs: {report['runs']}",
    ]
    for status, count in sorted(report["runs_by_status"].items()):
        lines.append(f"- {status}: {count}")
    lines += [
        "",
        "## Approvals",
        "",
        f"- Approved: {report['approvals_decided']['APPROVED']}",
        f"- Rejected: {report['approvals_decided']['REJECTED']}",
        f"- Pending now: {report['approvals_pending_now']}",
        "",
        "## Evals",
        "",
        f"- Scenarios run: {report['evals']['total']} "
        f"(passed {report['evals']['passed']}, failed {report['evals']['failed']})",
        "",
        "## Alerts fired",
        "",
    ]
    if report["alerts_fired"]:
        for alert in report["alerts_fired"]:
            lines.append(f"- [{alert['severity']}] {alert['rule']}: {alert['message']} ({alert['status']})")
    else:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the daily monitoring report.")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday, UTC)")
    args = parser.parse_args()
    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    db = SessionLocal()
    try:
        report = build_report(db, day)
    finally:
        db.close()
    directory = reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"daily-{day.isoformat()}.json"
    md_path = directory / f"daily-{day.isoformat()}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    print(f"Daily report written: {md_path} ({report['requests']} requests, "
          f"{report['runs']} runs, {len(report['alerts_fired'])} alerts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
