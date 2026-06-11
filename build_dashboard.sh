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
# Keep Next.js not-found.tsx output for site-wide 404 (do not overwrite with index).
if [ ! -f "$ROOT/app/dashboard-next/out/404.html" ] && [ -f "$ROOT/app/dashboard-next/out/index.html" ]; then
  cp "$ROOT/app/dashboard-next/out/index.html" "$ROOT/app/dashboard-next/out/404.html"
fi

if [ ! -f "$ROOT/app/dashboard-next/out/dashboard/index.html" ]; then
  echo "ERROR: build failed — missing out/dashboard/index.html" >&2
  exit 1
fi

# Fonts are served from /fonts (see app/dashboard/__init__.py). Next.js copies
# public/ into out/ automatically, but guard against a stale/partial export so
# Persian (Vazirmatn) and Latin (Inter) typography never silently falls back.
if [ -d "$ROOT/app/dashboard-next/public/fonts" ]; then
  mkdir -p "$ROOT/app/dashboard-next/out/fonts"
  cp -f "$ROOT/app/dashboard-next/public/fonts/"*.woff2 \
    "$ROOT/app/dashboard-next/out/fonts/" 2>/dev/null || true
fi

echo "==> Dashboard ready at app/dashboard-next/out/dashboard/"
