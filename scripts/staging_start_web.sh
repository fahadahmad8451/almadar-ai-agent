#!/usr/bin/env bash
# STAGING START WEB — Al Madar Holding AI Agent (v0.5)
#
# Serves the staging frontend build on :3101. The build is the same
# artifact as dev (relative /api paths); only the Vite proxy target
# differs (AMH_API_TARGET -> staging API :8101), so the browser still
# talks to one origin and the httpOnly cookies stay first-party.
# Requires the staging build: ./scripts/staging_build_web.sh
# (or: npm run build:staging in frontend/).
# Foreground — Ctrl+C stops it. Dev preview (:3100) is NOT touched.
#
# Usage:  ./scripts/staging_start_web.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$ROOT/frontend/dist-staging" ]; then
    echo "ERROR: frontend/dist-staging not found — run ./scripts/staging_build_web.sh first."
    exit 1
fi

echo "Staging web starting on http://127.0.0.1:3101 (API proxy -> :8101)"
echo "  (dev preview on :3100 is untouched — both can run side by side)"
cd "$ROOT/frontend"
AMH_API_TARGET=http://127.0.0.1:8101 exec npm run preview:staging
