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

# Terminate TLS with nginx and bind the app to localhost (IP or DOMAIN cert).
# Set DOMAIN=panel.example.com EMAIL=you@example.com to use a domain cert.
# Set SKIP_HTTPS=1 to skip (e.g. when fronted by an external load balancer).
if [ "${SKIP_HTTPS:-0}" != "1" ]; then
  echo "==> Enabling HTTPS (nginx reverse proxy + Let's Encrypt)"
  HTTPS_ARGS=()
  [ -n "${DOMAIN:-}" ] && HTTPS_ARGS+=(--domain "${DOMAIN}")
  [ -n "${EMAIL:-}" ]  && HTTPS_ARGS+=(--email "${EMAIL}")
  sudo -E bash ./scripts/setup_https.sh "${HTTPS_ARGS[@]}" || \
    echo "    (HTTPS setup skipped/failed — re-run: sudo ./scripts/setup_https.sh)"
fi

BASE_URL="${DOMAIN:+https://${DOMAIN}}"
[ -z "$BASE_URL" ] && BASE_URL="https://$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
echo "==> Done. Open ${BASE_URL}/dashboard/"
