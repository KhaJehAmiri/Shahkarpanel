#!/usr/bin/env bash
# Generate starter config: non-secrets in repo .env, secrets in /var/lib/nexuspanel/.env
# Run once per host. The sudo admin password is RANDOM and stored only as bcrypt hash.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DATA_DIR="${DATA_DIR:-/var/lib/nexuspanel}"
RUNTIME_ENV="${DATA_DIR}/.env"

if [ -f .env ] || [ -f "$RUNTIME_ENV" ]; then
  echo ".env or ${RUNTIME_ENV} already exists — remove them first for a fresh install" >&2
  exit 1
fi

rand() { openssl rand -hex 24 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 64; }

gen_password() {
  python3 - <<'PY' 2>/dev/null || openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 24
import secrets, string
alphabet = string.ascii_letters + string.digits
print(''.join(secrets.choice(alphabet) for _ in range(24)))
PY
}

bcrypt_hash() {
  python3 - "$1" <<'PY'
import sys
from passlib.hash import bcrypt
print(bcrypt.using(rounds=12).hash(sys.argv[1]))
PY
}

ADMIN_USER="${SUDO_USERNAME:-admin}"
ADMIN_PASS="$(gen_password)"
HASH="$(bcrypt_hash "$ADMIN_PASS")" || { echo "passlib/bcrypt missing — run: pip install -r requirements.txt" >&2; exit 1; }

PUBLIC_IP="$(curl -fsSL --max-time 6 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$PUBLIC_IP" ] || PUBLIC_IP="127.0.0.1"

REDIS_PW="$(rand)"
NODE_BOOT="$(rand)"
NODE_CTRL="$(rand)"
METRICS="$(rand)"

mkdir -p "$DATA_DIR"
cp .env.example .env
printf '\n' >> .env

append_repo() { grep -q "^${1}=" .env 2>/dev/null || echo "${1}=${2}" >> .env; }

append_repo "UVICORN_HOST" "127.0.0.1"
append_repo "UVICORN_PORT" "8000"
append_repo "ALLOWED_ORIGINS" "http://127.0.0.1:8000"
append_repo "PANEL_PUBLIC_ADDRESS" "http://${PUBLIC_IP}:8000"
append_repo "SQLALCHEMY_DATABASE_URL" "sqlite:////var/lib/nexuspanel/db.sqlite3"

chmod 600 .env

cat > "$RUNTIME_ENV" <<EOF
# Runtime secrets — outside git checkout
SUDO_USERNAME=${ADMIN_USER}
SUDO_PASSWORD_HASH=${HASH}
REDIS_PASSWORD=${REDIS_PW}
REDIS_URL=redis://:${REDIS_PW}@127.0.0.1:6379/0
NODE_BOOTSTRAP_TOKEN=${NODE_BOOT}
NODE_CONTROL_SECRET=${NODE_CTRL}
METRICS_TOKEN=${METRICS}
EOF
chmod 600 "$RUNTIME_ENV"

cat <<EOF

Created:
  ${ROOT}/.env              (repo config — safe to diff, no secrets)
  ${RUNTIME_ENV}            (runtime secrets — never commit)

  Admin username : ${ADMIN_USER}
  Admin password : ${ADMIN_PASS}

  ↳ SAVE THIS PASSWORD NOW. It is not stored in plaintext anywhere.

Next steps:
  1. Start the panel (systemd or docker compose -f docker-compose.postgres.yml up -d).
  2. Enable HTTPS: sudo scripts/setup_https.sh
EOF
