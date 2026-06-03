#!/usr/bin/env bash
# Build the NexusPanel dashboard. Phase 7 ships a brand-new UI in
# app/dashboard-v2; we build that and fall back to the legacy dashboard only if
# the v2 sources are missing.
set -e
cd "$(dirname "$0")"

if [ -f app/dashboard-v2/package.json ]; then
  echo "==> Building NexusPanel dashboard (v2)…"
  cd app/dashboard-v2
  npm install
  VITE_BASE_API=/api/ npm run build
  cp ./build/index.html ./build/404.html
else
  echo "==> Building legacy dashboard…"
  cd app/dashboard
  VITE_BASE_API=/api/ npm run build --if-present -- --outDir build --assetsDir statics
  cp ./build/index.html ./build/404.html
fi
