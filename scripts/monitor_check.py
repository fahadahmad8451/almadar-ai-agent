"""Monitoring alert check — v0.9.0.

Probes the API health endpoint, then evaluates the six locked alert
rules against the live PostgreSQL database (see
app/services/monitoring.py). Alerts are written to the alerts table
with 30-minute dedup per rule; conditions that cleared are
auto-resolved.

Exit codes: 0 = healthy, no active alert; 1 = at least one active
alert (HIGH/MEDIUM); 2 = CRITICAL alert active, or the API/database
is down.

Usage:
    AMH_ENV_FILE=.env.production python scripts/monitor_check.py --api-url http://127.0.0.1:8100
    AMH_ENV_FILE=.env.staging    python scripts/monitor_check.py --api-url http://127.0.0.1:8101

Production runs this every 5 minutes from the in-process scheduler
(MONITORING_ALERTS_ENABLED=true); this script is the same check for
manual runs and for Fahad's PC (Task Scheduler / cron — see
docs/MONITORING.md).
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from app.db import models  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services import monitoring as monitoring_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check monitoring alert rules.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8100")
    args = parser.parse_args()

    api_available = True
    try:
        response = httpx.get(
            f"{args.api_url.rstrip('/')}/api/v1/health", timeout=10, trust_env=False
        )
        api_available = response.status_code == 200 and response.json().get("success") is True
    except Exception:  # noqa: BLE001 - unreachable API is the signal
        api_available = False
    if not api_available:
        print(f"[CRITICAL] api_down — health endpoint unreachable at {args.api_url}.")

    db = SessionLocal()
    try:
        result = monitoring_service.check_alerts(db, api_available=api_available)
    finally:
        db.close()
    for rule in result["fired"]:
        severity = monitoring_service.RULES[rule]["severity"]
        print(f"[{severity}] {rule} — fired.")
    for rule in result["skipped"]:
        print(f"[dedup] {rule} — already ACTIVE within 30 minutes, not duplicated.")
    for rule in result["cleared"]:
        print(f"[resolved] {rule} — condition cleared, alert auto-resolved.")
    if not result["fired"] and not result["skipped"] and not result["cleared"]:
        print("OK — no alerts.")

    db = SessionLocal()
    try:
        active = (
            db.query(models.Alert).filter(models.Alert.status == "ACTIVE").order_by(models.Alert.id).all()
        )
    finally:
        db.close()
    if not result["db_available"]:
        return 2
    if any(a.severity == "CRITICAL" for a in active) or not api_available:
        return 2
    if active:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
