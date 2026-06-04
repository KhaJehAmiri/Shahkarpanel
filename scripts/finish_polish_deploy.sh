#!/usr/bin/env bash
# Finish system-polish phase: build dashboard, restart panel, smoke APIs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> NexusPanel version: $(cat VERSION 2>/dev/null || echo unknown)"

echo "==> pytest"
python3 -m pytest -q --tb=no

echo "==> build dashboard-next"
bash ./build_dashboard.sh

if command -v docker >/dev/null 2>&1; then
  if [ -f docker-compose.postgres.yml ]; then
    echo "==> docker compose build + restart nexuspanel"
    docker compose -f docker-compose.postgres.yml build nexuspanel
    docker compose -f docker-compose.postgres.yml up -d nexuspanel
    docker compose -f docker-compose.postgres.yml ps
  elif [ -f docker-compose.yml ]; then
    docker compose -f docker-compose.yml up -d --build
    docker compose -f docker-compose.yml ps
  fi
fi

echo "==> smoke (local API if up)"
code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ 2>/dev/null || echo 000)"
echo "GET / -> HTTP ${code}"
echo "Done. Hard-refresh /dashboard/ in the browser."
