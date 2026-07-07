#!/usr/bin/env bash
# Put a VLESS gRPC inbound behind nginx + CDN (domain :443 → 127.0.0.1:<xray-port>).
#
# Usage:
#   sudo scripts/setup_grpc_cdn.sh --domain nex.tehranmap.xyz --tag ssg --port 2080 --service myservice-443
#   sudo scripts/setup_grpc_cdn.sh --domain nex.example.com --email admin@example.com
#
# Requires: Cloudflare gRPC enabled (Network → gRPC) when using orange-cloud proxy.
set -euo pipefail

DOMAIN="${DOMAIN:-nex.tehranmap.xyz}"
EMAIL="${EMAIL:-}"
INBOUND_TAG="${INBOUND_TAG:-ssg}"
XRAY_PORT="${XRAY_PORT:-2080}"
SERVICE_NAME="${SERVICE_NAME:-myservice-443}"
WEBROOT="/var/www/letsencrypt"
NGINX_SITE="/etc/nginx/sites-available/nexuspanel-grpc-${INBOUND_TAG}"
XRAY_JSON="${XRAY_JSON:-/var/lib/nexuspanel/xray_config.json}"

RED=$'\e[31m'; GREEN=$'\e[32m'; BLUE=$'\e[34m'; NC=$'\e[0m'
log() { echo "${BLUE}[*]${NC} $*"; }
ok() { echo "${GREEN}[✓]${NC} $*"; }
die() { echo "${RED}[x]${NC} $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2;;
    --email) EMAIL="${2:-}"; shift 2;;
    --tag) INBOUND_TAG="${2:-}"; shift 2;;
    --port) XRAY_PORT="${2:-}"; shift 2;;
    --service) SERVICE_NAME="${2:-}"; shift 2;;
    *) die "Unknown arg: $1";;
  esac
done

[ "$(id -u)" -eq 0 ] || die "Run as root (sudo)."
[ -n "$DOMAIN" ] || die "DOMAIN is required"
[ -f "$XRAY_JSON" ] || die "Missing Xray config: $XRAY_JSON"

mkdir -p "$WEBROOT"

CERTBOT="${CERTBOT:-/opt/certbot-venv/bin/certbot}"
if [ ! -x "$CERTBOT" ]; then
  CERTBOT="$(command -v certbot || true)"
fi
[ -n "$CERTBOT" ] && [ -x "$CERTBOT" ] || die "certbot not found (install certbot or set CERTBOT=...)"
if [ ! -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
  log "Requesting Let's Encrypt certificate for ${DOMAIN}..."
  EMAIL_ARGS=()
  [ -n "$EMAIL" ] && EMAIL_ARGS=(--email "$EMAIL" --no-eff-email) || EMAIL_ARGS=(--register-unsafely-without-email)
  "$CERTBOT" certonly --webroot -w "$WEBROOT" -d "$DOMAIN" "${EMAIL_ARGS[@]}" \
    --agree-tos --non-interactive \
    || die "certbot failed — ensure DNS for ${DOMAIN} points to this server (CF proxy OK for HTTP-01)."
  ok "Certificate issued for ${DOMAIN}"
else
  ok "Certificate already present for ${DOMAIN}"
fi

log "Writing nginx gRPC vhost (${NGINX_SITE})..."
cat > "$NGINX_SITE" <<EOF
# VLESS gRPC (${INBOUND_TAG}) — CDN edge TLS → plain gRPC on 127.0.0.1:${XRAY_PORT}
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
    }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location ~ ^/${SERVICE_NAME} {
        grpc_pass grpc://127.0.0.1:${XRAY_PORT};
        grpc_set_header Host \$host;
        grpc_set_header X-Real-IP \$remote_addr;
        grpc_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        grpc_read_timeout 1h;
        grpc_send_timeout 1h;
    }

    location / { return 444; }
}
EOF

ln -sf "$NGINX_SITE" "/etc/nginx/sites-enabled/nexuspanel-grpc-${INBOUND_TAG}"
nginx -t || die "nginx -t failed"
systemctl reload nginx
ok "nginx reloaded with gRPC proxy for ${DOMAIN}:443 → 127.0.0.1:${XRAY_PORT}"

log "Patching Xray inbound ${INBOUND_TAG} for CDN (plain gRPC on loopback)..."
python3 - <<PY
import json
from pathlib import Path

path = Path("${XRAY_JSON}")
data = json.loads(path.read_text())
changed = False
for ib in data.get("inbounds") or []:
    if ib.get("tag") != "${INBOUND_TAG}":
        continue
    ib["listen"] = "127.0.0.1"
    ib["port"] = int("${XRAY_PORT}")
    stream = ib.setdefault("streamSettings", {})
    stream["network"] = "grpc"
    stream["security"] = "none"
    stream.pop("tlsSettings", None)
    stream.pop("realitySettings", None)
    gs = stream.setdefault("grpcSettings", {})
    gs["serviceName"] = "${SERVICE_NAME}"
    changed = True
    break

if not changed:
    raise SystemExit("inbound tag ${INBOUND_TAG} not found")

path.write_text(json.dumps(data, indent=4))
print("patched", path)
PY

ok "Xray config updated: ${INBOUND_TAG} → 127.0.0.1:${XRAY_PORT} grpc (no TLS)"

echo
echo "Next steps:"
echo "  1. Cloudflare → Network → enable gRPC (orange-cloud proxy on ${DOMAIN})"
echo "  2. SSL/TLS mode: Full (strict) recommended"
echo "  3. docker compose -f /opt/nexuspanel/docker-compose.yml restart nexuspanel"
echo "  4. Subscription host: address=${DOMAIN}, port=443"
echo "  5. Users refresh subscription in client"
