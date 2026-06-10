#!/usr/bin/env bash
# Generate a starter .env from .env.example with strong random secrets.
# Run once per host. The sudo admin password is RANDOM (never a default) and is
# stored only as a bcrypt hash — the plaintext is printed once, here, then gone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  echo ".env already exists — remove it first if you want a fresh file" >&2
  exit 1
fi

rand() { openssl rand -hex 24 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 64; }

# A strong, human-typable password (no ambiguous chars), 24 alnum characters.
gen_password() {
  python3 - <<'PY' 2>/dev/null || openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 24
import secrets, string
alphabet = string.ascii_letters + string.digits
print(''.join(secrets.choice(alphabet) for _ in range(24)))
PY
}

bcrypt_hash() { # $1 = plaintext
  python3 - "$1" <<'PY'
import sys
from passlib.hash import bcrypt
print(bcrypt.using(rounds=12).hash(sys.argv[1]))
PY
}

ADMIN_USER="${SUDO_USERNAME:-admin}"
ADMIN_PASS="$(gen_password)"
HASH="$(bcrypt_hash "$ADMIN_PASS")" || { echo "passlib/bcrypt missing — run: pip install -r requirements.txt" >&2; exit 1; }

# Detect a public address for node provisioning callbacks (best effort).
PUBLIC_IP="$(curl -fsSL --max-time 6 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$PUBLIC_IP" ] || PUBLIC_IP="127.0.0.1"

cp .env.example .env
# .env.example may end without a newline; avoid gluing the first append.
printf '\n' >> .env

append() { grep -q "^${1}=" .env 2>/dev/null || echo "${1}=${2}" >> .env; }

REDIS_PW="$(rand)"
append "SQLALCHEMY_DATABASE_URL" "sqlite:////var/lib/nexuspanel/db.sqlite3"
append "NODE_BOOTSTRAP_TOKEN" "$(rand)"
append "NODE_CONTROL_SECRET" "$(rand)"
append "METRICS_TOKEN" "$(rand)"
append "REDIS_PASSWORD" "$REDIS_PW"
# Bind to localhost by default — TLS is terminated by nginx (scripts/setup_https.sh).
append "UVICORN_HOST" "127.0.0.1"
append "UVICORN_PORT" "8000"
append "ALLOWED_ORIGINS" "http://127.0.0.1:8000"
append "PANEL_PUBLIC_ADDRESS" "http://${PUBLIC_IP}:8000"
append "SUDO_USERNAME" "$ADMIN_USER"
append "SUDO_PASSWORD_HASH" "$HASH"

chmod 600 .env

cat <<EOF

Created .env with random secrets (bcrypt-hashed admin password).

  Admin username : ${ADMIN_USER}
  Admin password : ${ADMIN_PASS}

  ↳ SAVE THIS PASSWORD NOW. It is not stored in plaintext anywhere.
    Only its bcrypt hash is written to .env (SUDO_PASSWORD_HASH).

Next steps:
  1. Start the panel (systemd or docker).
  2. Enable HTTPS + reverse proxy:  sudo scripts/setup_https.sh            # IP cert
                                    sudo scripts/setup_https.sh --domain panel.example.com --email you@example.com
EOF
