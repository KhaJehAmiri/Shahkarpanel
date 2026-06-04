#!/usr/bin/env bash
# Deploy NexusPanel on this host (production checklist).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "ERROR: create .env from .env.example first" >&2
  exit 1
fi

echo "==> Pull latest"
git pull origin master

echo "==> Build dashboard-next"
./build_dashboard.sh

if command -v docker >/dev/null 2>&1; then
  echo "==> Docker compose up"
  docker compose -f docker-compose.postgres.yml up -d --build
  docker compose -f docker-compose.postgres.yml ps
else
  echo "==> Docker not found — install deps and run panel directly:"
  echo "    pip install -r requirements.txt && alembic upgrade head && python main.py"
fi

echo "==> Done. Open http://$(hostname -I | awk '{print $1}'):8000/dashboard/"
