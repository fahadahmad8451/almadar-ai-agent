#!/usr/bin/env bash
# STAGING STOP — Al Madar Holding AI Agent (v0.5)
#
# Stops the staging API (:8101) and staging web preview (:3101).
# Dev (:8100 / :3100) is NOT touched.
#
# Usage:  ./scripts/staging_stop.sh
set -u

pkill -f "uvicorn app.main:app --port 8101" 2>/dev/null || true
pkill -f "vite preview --port 3101" 2>/dev/null || true
sleep 1
if pgrep -f "uvicorn app.main:app --port 8101" >/dev/null 2>&1; then
    echo "WARNING: staging API still running."
else
    echo "Staging API stopped."
fi
if pgrep -f "vite preview --port 3101" >/dev/null 2>&1; then
    echo "WARNING: staging web still running."
else
    echo "Staging web stopped."
fi
