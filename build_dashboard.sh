#!/usr/bin/env bash
# Build the NexusPanel UI (dashboard-next only).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$ROOT/app/dashboard-next/package.json" ]; then
  echo "ERROR: app/dashboard-next/package.json not found" >&2
  exit 1
fi

echo "==> Building NexusPanel dashboard-next (Next.js static export)…"
(
  cd "$ROOT/app/dashboard-next"
  npm install
  NEXT_PUBLIC_BASE_API=/api/ npm run build
)

if [ -f "$ROOT/app/dashboard-next/out/dashboard/index.html" ]; then
  cp "$ROOT/app/dashboard-next/out/dashboard/index.html" \
    "$ROOT/app/dashboard-next/out/dashboard/404.html"
fi
if [ -f "$ROOT/app/dashboard-next/out/index.html" ]; then
  cp "$ROOT/app/dashboard-next/out/index.html" "$ROOT/app/dashboard-next/out/404.html"
fi

if [ ! -f "$ROOT/app/dashboard-next/out/dashboard/index.html" ]; then
  echo "ERROR: build failed — missing out/dashboard/index.html" >&2
  exit 1
fi

echo "==> Dashboard ready at app/dashboard-next/out/dashboard/"
