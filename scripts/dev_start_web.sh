#!/usr/bin/env bash
# Start the frontend web app (dev, :3100). Local-first, no Docker.
set -e
cd "$(dirname "$0")/../frontend"
if [ ! -d node_modules ]; then
  npm install
fi
exec npm run dev
