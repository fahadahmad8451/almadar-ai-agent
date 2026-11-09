#!/usr/bin/env bash
# STAGING BUILD WEB — Al Madar Holding AI Agent (v0.5)
#
# Builds the staging frontend into frontend/dist-staging (dev's
# frontend/dist is NOT touched). The build is environment-agnostic
# (relative /api paths); the API target is set at preview time by
# AMH_API_TARGET in scripts/staging_start_web.sh.
#
# Usage:  ./scripts/staging_build_web.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
npm run build:staging
echo "Staging web build done: frontend/dist-staging"
