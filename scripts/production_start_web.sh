#!/usr/bin/env bash
# PRODUCTION START WEB — Al Madar Holding AI Agent (v0.8.0)
#
# Serves the production frontend build on :3100 (vite preview).
# Rebuild first after any frontend change:
#   cd frontend && npm run build
# The production API must be running on :8100 first.
#
# Usage:  ./scripts/production_start_web.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$ROOT/frontend/dist" ]; then
    echo "ERROR: frontend/dist not found — run 'cd frontend && npm run build' first."
    exit 1
fi

echo "Stopping dev web preview (production reuses port 3100)..."
pkill -f "vite preview --port 3100" 2>/dev/null || true
sleep 1

echo "Production web starting on http://127.0.0.1:3100"
cd "$ROOT/frontend"
exec npx vite preview --port 3100 --host 127.0.0.1
