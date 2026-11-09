#!/usr/bin/env bash
# Start the backend API (dev, :8100). Local-first, no Docker.
set -e
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r backend/requirements.txt
exec .venv/bin/uvicorn app.main:app --port 8100 --app-dir backend
