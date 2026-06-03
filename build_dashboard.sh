#!/usr/bin/env bash
# Build the NexusPanel dashboard. Phase 7 ships dashboard-v2 (Vite/React).
# Phase 9 adds dashboard-next (Next.js 14 static export) which hosts the new
# subscription page (/subscribe/). Both bundles coexist; FastAPI prefers the
# Next.js bundle for the sub page when present.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$ROOT/app/dashboard-v2/package.json" ]; then
  echo "==> Building NexusPanel dashboard-v2 (Vite/React)…"
  (cd "$ROOT/app/dashboard-v2" && npm install && VITE_BASE_API=/api/ npm run build && cp ./build/index.html ./build/404.html)
fi

if [ -f "$ROOT/app/dashboard-next/package.json" ]; then
  echo "==> Building NexusPanel dashboard-next (Next.js 14 static export)…"
  (cd "$ROOT/app/dashboard-next" && npm install && npm run build)
fi

if [ ! -f "$ROOT/app/dashboard-v2/build/index.html" ] && [ ! -f "$ROOT/app/dashboard/build/index.html" ]; then
  echo "==> Building legacy dashboard…"
  (cd "$ROOT/app/dashboard" && VITE_BASE_API=/api/ npm run build --if-present -- --outDir build --assetsDir statics && cp ./build/index.html ./build/404.html)
fi
