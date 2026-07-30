#!/usr/bin/env bash
# Run Shahkar on this host without Docker (dev / single-node).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "Run ./scripts/setup_env.sh first" >&2
  exit 1
fi

mkdir -p /var/lib/shahkar
if ! grep -q '^SQLALCHEMY_DATABASE_URL=' .env 2>/dev/null; then
  echo "SQLALCHEMY_DATABASE_URL missing in .env" >&2
  exit 1
fi

pip install -q -r requirements.txt
alembic upgrade head
exec python3 main.py
