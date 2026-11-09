#!/usr/bin/env bash
# STAGING START — Al Madar Holding AI Agent (v0.5)
#
# Starts the staging API on :8101 with staging env loaded from
# .env.staging (AMH_ENV_FILE). Foreground — Ctrl+C stops it.
# Dev (port 8100) is NOT touched and can run at the same time.
# Scheduler is OFF in staging (SCHEDULER_ENABLED=false).
#
# Usage:  ./scripts/staging_start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$ROOT/.env.staging" ]; then
    echo "ERROR: $ROOT/.env.staging not found — run ./scripts/staging_setup.sh first."
    exit 1
fi
if [ ! -d "$ROOT/.venv" ]; then
    echo "ERROR: venv not found at $ROOT/.venv — run ./scripts/dev_start.sh once first."
    exit 1
fi

echo "Staging API starting on http://127.0.0.1:8101"
echo "  AMH_ENV_FILE=.env.staging  ENVIRONMENT=staging  DATABASE=almadar_agent_staging"
echo "  Scheduler: OFF (manual runs only)"
echo "  (dev on :8100 is untouched — both can run side by side)"
cd "$ROOT"
AMH_ENV_FILE=.env.staging exec "$ROOT/.venv/bin/uvicorn" app.main:app --port 8101 --host 127.0.0.1 --app-dir backend
