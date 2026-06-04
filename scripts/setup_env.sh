#!/usr/bin/env bash
# Generate a starter .env from .env.example with random secrets (run once per host).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  echo ".env already exists — remove it first if you want a fresh file" >&2
  exit 1
fi

rand() { openssl rand -hex 24 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 64; }
bcrypt_placeholder() {
  python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('changeme'))" 2>/dev/null || echo ""
}

cp .env.example .env
HASH=$(bcrypt_placeholder)

append() {
  grep -q "^${1}=" .env 2>/dev/null || echo "${1}=${2}" >> .env
}

append "SQLALCHEMY_DATABASE_URL" "sqlite:////var/lib/nexuspanel/db.sqlite3"
append "NODE_BOOTSTRAP_TOKEN" "$(rand)"
append "NODE_CONTROL_SECRET" "$(rand)"
append "METRICS_TOKEN" "$(rand)"
append "REDIS_PASSWORD" "$(rand)"
append "ALLOWED_ORIGINS" "http://127.0.0.1:8000"

if [ -n "$HASH" ]; then
  append "SUDO_USERNAME" "admin"
  append "SUDO_PASSWORD_HASH" "$HASH"
  echo "# Default sudo password after setup: changeme — change immediately" >> .env
fi

echo "Created .env — edit ALLOWED_ORIGINS and secrets before production."
echo "If SUDO_PASSWORD_HASH was set, initial login password is: changeme"
