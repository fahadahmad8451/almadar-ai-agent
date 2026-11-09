#!/usr/bin/env bash
# PRODUCTION STOP — Al Madar Holding AI Agent (v0.8.0)
#
# Stops the production API (:8100) and production web preview (:3100).
# Dev (:8100 / :3100 use the same ports) and staging (:8101 / :3101)
# are NOT touched by this script — restart dev afterwards with
# ./scripts/dev_start.sh (+ dev_start_web.sh).
#
# Usage:  ./scripts/production_stop.sh
set -u

pkill -f "uvicorn app.main:app --port 8100" 2>/dev/null || true
pkill -f "vite preview --port 3100" 2>/dev/null || true
sleep 1
if pgrep -f "uvicorn app.main:app --port 8100" >/dev/null 2>&1; then
    echo "WARNING: production API still running."
else
    echo "Production API stopped."
fi
if pgrep -f "vite preview --port 3100" >/dev/null 2>&1; then
    echo "WARNING: production web still running."
else
    echo "Production web stopped."
fi
