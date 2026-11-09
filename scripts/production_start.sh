#!/usr/bin/env bash
# PRODUCTION START — Al Madar Holding AI Agent (v0.8.0)
#
# Starts the production API on :8100 with production env loaded from
# .env.production (AMH_ENV_FILE). Foreground — Ctrl+C stops it.
#
# Production REUSES the dev ports (API 8100 / Web 3100), so the dev
# servers are stopped first (same rule as Project 1). Dev data is
# untouched — only the ports are freed. Restart dev afterwards with
# ./scripts/dev_start.sh (+ dev_start_web.sh).
#
# Scheduler is ON in production (the three locked jobs fire on their
# schedule, running as the Admin created by create_admin.py).
# --no-server-header hides the Server header (hardening, v0.8.0).
#
# Usage:  ./scripts/production_start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$ROOT/.env.production" ]; then
    echo "ERROR: $ROOT/.env.production not found — run ./scripts/production_setup.sh first."
    exit 1
fi
if [ ! -d "$ROOT/.venv" ]; then
    echo "ERROR: venv not found at $ROOT/.venv — run ./scripts/dev_start.sh once first."
    exit 1
fi

echo "Stopping dev servers (production reuses ports 8100/3100)..."
pkill -f "uvicorn app.main:app --port 8100" 2>/dev/null || true
pkill -f "vite preview --port 3100" 2>/dev/null || true
sleep 1

echo "Production API starting on http://127.0.0.1:8100"
echo "  AMH_ENV_FILE=.env.production  ENVIRONMENT=production  DATABASE=almadar_agent_prod"
echo "  Demo accounts: OFF · Scheduler: ON · CORS: localhost:3100 only"
cd "$ROOT"
AMH_ENV_FILE=.env.production exec "$ROOT/.venv/bin/uvicorn" app.main:app --port 8100 --host 127.0.0.1 --app-dir backend --no-server-header
