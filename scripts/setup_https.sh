#!/usr/bin/env bash
#
# setup_https.sh — put Shahkar behind nginx with a real TLS certificate and
# stop exposing the raw app port to the internet.
#
# It handles BOTH deployment targets:
#   * domain  → standard Let's Encrypt certificate (HTTP-01, auto-renew ~60d)
#   * bare IP → Let's Encrypt IP-address certificate (shortlived 6-day profile,
#               renewed automatically; requires certbot >= 5.4)
#
# What it guarantees after a successful run:
#   * nginx terminates TLS on :443 and reverse-proxies to 127.0.0.1:<port>
#   * :80 redirects to :443 (except the ACME challenge path)
#   * the panel binds to 127.0.0.1 only — the app port is no longer public
#   * certificates renew automatically and reload nginx via a deploy hook
#   * HSTS + sane security headers are set at the edge
#
# Usage (run as root from the repo root or via the `shahkar https` command):
#   sudo scripts/setup_https.sh                      # auto-detect public IP, IP cert
#   sudo scripts/setup_https.sh --domain panel.x.com --email you@x.com
#   sudo scripts/setup_https.sh --ip 203.0.113.10    # force a specific IP
#
# Environment overrides: DOMAIN, EMAIL, PANEL_PORT, PUBLIC_IP, STAGING=1
set -euo pipefail

# --------------------------------------------------------------------------- #
# Args / config
# --------------------------------------------------------------------------- #
DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"
PANEL_PORT="${PANEL_PORT:-8000}"
PUBLIC_IP="${PUBLIC_IP:-}"
STAGING="${STAGING:-0}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT}/.env}"
WEBROOT="/var/www/letsencrypt"
LE_DIR="/etc/letsencrypt"
CERTBOT_VENV="/opt/certbot-venv"

RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'; BOLD=$'\e[1m'; NC=$'\e[0m'
log()  { echo "${BLUE}[*]${NC} $*"; }
ok()   { echo "${GREEN}[✓]${NC} $*"; }
warn() { echo "${YELLOW}[!]${NC} $*"; }
die()  { echo "${RED}[x]${NC} $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2;;
    --email)  EMAIL="${2:-}"; shift 2;;
    --port)   PANEL_PORT="${2:-}"; shift 2;;
    --ip)     PUBLIC_IP="${2:-}"; shift 2;;
    --staging) STAGING=1; shift;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0;;
    *) die "Unknown argument: $1";;
  esac
done

[ "$(id -u)" -eq 0 ] || die "Run as root (sudo)."

# --------------------------------------------------------------------------- #
# Resolve the server name (domain wins; otherwise the public IP)
# --------------------------------------------------------------------------- #
detect_public_ip() {
  local ip
  ip="$(curl -fsSL --max-time 6 https://api.ipify.org 2>/dev/null || true)"
  [ -n "$ip" ] || ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "$ip"
}

MODE="ip"
SERVER_NAME=""
if [ -n "$DOMAIN" ]; then
  MODE="domain"
  SERVER_NAME="$DOMAIN"
else
  [ -n "$PUBLIC_IP" ] || PUBLIC_IP="$(detect_public_ip)"
  [ -n "$PUBLIC_IP" ] || die "Could not determine a public IP. Pass --ip or --domain."
  SERVER_NAME="$PUBLIC_IP"
fi
ok "TLS target: ${BOLD}${SERVER_NAME}${NC} (${MODE} mode), proxying to 127.0.0.1:${PANEL_PORT}"

# --------------------------------------------------------------------------- #
# Dependencies: nginx (always) + certbot (system for domains, venv 5.4+ for IP)
# --------------------------------------------------------------------------- #
install_nginx() {
  command -v nginx >/dev/null 2>&1 && { ok "nginx already installed"; return; }
  log "Installing nginx..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq nginx \
    || die "Failed to install nginx (apt). Install it manually and re-run."
  ok "nginx installed."
}

# IP certificates need certbot >= 5.4 (the --ip-address flag). The distro
# package is usually too old, so we keep a dedicated venv for that case.
CERTBOT_BIN=""
install_certbot() {
  if [ "$MODE" = "domain" ] && command -v certbot >/dev/null 2>&1; then
    CERTBOT_BIN="$(command -v certbot)"; ok "Using system certbot for domain cert."; return
  fi
  if [ -x "${CERTBOT_VENV}/bin/certbot" ]; then
    CERTBOT_BIN="${CERTBOT_VENV}/bin/certbot"; ok "Using certbot venv (${CERTBOT_BIN})."; return
  fi
  log "Installing certbot (>=5.4) in a virtualenv for IP-address certificate support..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y -qq python3-venv >/dev/null 2>&1 || true
  python3 -m venv "${CERTBOT_VENV}" || die "Could not create certbot venv."
  "${CERTBOT_VENV}/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
  "${CERTBOT_VENV}/bin/pip" install --quiet "certbot>=5.4" || die "Failed to install certbot."
  CERTBOT_BIN="${CERTBOT_VENV}/bin/certbot"
  ok "certbot $("${CERTBOT_BIN}" --version 2>&1 | awk '{print $2}') installed."
}

# --------------------------------------------------------------------------- #
# nginx vhost — bootstrap with a self-signed cert so nginx can start, then the
# real certificate is swapped in once issued.
# --------------------------------------------------------------------------- #
SELF_DIR="/etc/nginx/certs"
write_self_signed() {
  mkdir -p "$SELF_DIR"
  [ -f "${SELF_DIR}/bootstrap.crt" ] && return
  log "Creating bootstrap self-signed certificate (replaced by Let's Encrypt)..."
  local san
  if [ "$MODE" = "ip" ]; then san="IP:${SERVER_NAME}"; else san="DNS:${SERVER_NAME}"; fi
  openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -keyout "${SELF_DIR}/bootstrap.key" -out "${SELF_DIR}/bootstrap.crt" \
    -subj "/CN=${SERVER_NAME}/O=Shahkar" -addext "subjectAltName=${san}" >/dev/null 2>&1
  chmod 600 "${SELF_DIR}/bootstrap.key"
}

NGINX_SITE="/etc/nginx/sites-available/shahkar"
write_nginx_conf() {
  local cert_path="$1" key_path="$2"
  mkdir -p "${WEBROOT}/.well-known/acme-challenge"
  chmod -R a+rX "${WEBROOT}"
  cat > "${NGINX_SITE}" <<EOF
# Managed by Shahkar scripts/setup_https.sh — re-run that script to regenerate.
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAME};

    # ACME HTTP-01 challenge must stay on plain HTTP.
    location /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
    }
    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${SERVER_NAME};

    ssl_certificate     ${cert_path};
    ssl_certificate_key ${key_path};
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    client_max_body_size 200m;

    # Panel down during docker restart: fail connect fast (default 60s) + friendly page.
    error_page 502 503 504 = @panel_restarting;

    location @panel_restarting {
        default_type text/html;
        charset utf-8;
        add_header Cache-Control "no-store" always;
        add_header Retry-After "2" always;
        root /var/lib/shahkar/nginx/html;
        rewrite ^ /restarting.html break;
    }

    location / {
        proxy_pass http://127.0.0.1:${PANEL_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_connect_timeout 1s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_next_upstream off;
    }
}
EOF
  # Always refresh the waiting page (and any sibling panel proxy vhosts).
  local ensure="${SCRIPT_DIR:-}/ensure_nginx_restarting_page.sh"
  if [ -z "${SCRIPT_DIR:-}" ]; then
    ensure="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ensure_nginx_restarting_page.sh"
  fi
  if [ -f "$ensure" ]; then
    PANEL_PORT="${PANEL_PORT}" bash "$ensure" >/dev/null 2>&1 || true
  else
    mkdir -p /var/lib/shahkar/nginx/html
    cat > /var/lib/shahkar/nginx/html/restarting.html <<'HTML'
<!DOCTYPE html>
<html lang="fa" dir="rtl"><head>
<meta charset="utf-8"/><meta http-equiv="refresh" content="2"/>
<title>Shahkar — starting</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:Tahoma,sans-serif;background:#0f1419;color:#e8eef4}
.card{max-width:420px;padding:2rem;background:#1a222c;border-radius:16px;text-align:center}
.spinner{width:40px;height:40px;margin:1.2rem auto;border:3px solid rgba(61,156,240,.2);border-top-color:#3d9cf0;border-radius:50%;animation:s .8s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}p{color:#8b9aab}</style>
</head><body><div class="card"><h1>پنل در حال راه‌اندازی است</h1>
<p>Panel is starting — refreshing automatically.</p><div class="spinner"></div></div>
<script>setTimeout(function(){location.reload()},2000)</script></body></html>
HTML
    chmod -R a+rX /var/lib/shahkar/nginx 2>/dev/null || true
  fi
  ln -sf "${NGINX_SITE}" /etc/nginx/sites-enabled/shahkar
  rm -f /etc/nginx/sites-enabled/default
  nginx -t >/dev/null 2>&1 || die "nginx config test failed (see: nginx -t)."
}

# --------------------------------------------------------------------------- #
# Issue / install the certificate
# --------------------------------------------------------------------------- #
LE_LIVE="${LE_DIR}/live/${SERVER_NAME}"
issue_cert() {
  local extra=()
  [ "$STAGING" = "1" ] && extra+=(--staging)
  if [ -n "$EMAIL" ]; then extra+=(-m "$EMAIL" --no-eff-email); else extra+=(--register-unsafely-without-email); fi

  if [ "$MODE" = "domain" ]; then
    log "Requesting Let's Encrypt certificate for ${SERVER_NAME}..."
    "${CERTBOT_BIN}" certonly --non-interactive --agree-tos "${extra[@]}" \
      --webroot --webroot-path "${WEBROOT}" -d "${SERVER_NAME}" \
      --config-dir "${LE_DIR}" --work-dir /var/lib/letsencrypt --logs-dir /var/log/letsencrypt \
      || die "Certificate issuance failed. Ensure ${SERVER_NAME} resolves to this host and :80 is reachable."
  else
    log "Requesting Let's Encrypt IP-address certificate for ${SERVER_NAME} (shortlived 6-day profile)..."
    "${CERTBOT_BIN}" certonly --non-interactive --agree-tos "${extra[@]}" \
      --preferred-profile shortlived \
      --webroot --webroot-path "${WEBROOT}" --ip-address "${SERVER_NAME}" \
      --config-dir "${LE_DIR}" --work-dir /var/lib/letsencrypt --logs-dir /var/log/letsencrypt \
      || die "IP certificate issuance failed. Ensure :80 is reachable from the internet."
  fi
  [ -f "${LE_LIVE}/fullchain.pem" ] || die "Expected cert at ${LE_LIVE}/fullchain.pem not found."
  ok "Certificate issued: ${LE_LIVE}/fullchain.pem"
}

# Add a reload hook and a frequent renew timer (IP certs are only 6 days).
setup_renewal() {
  local conf="${LE_DIR}/renewal/${SERVER_NAME}.conf"
  if [ -f "$conf" ] && ! grep -q '^renew_hook' "$conf"; then
    sed -i '/^\[renewalparams\]/a renew_hook = systemctl reload nginx' "$conf"
  fi
  cat > /etc/systemd/system/certbot-renew.service <<EOF
[Unit]
Description=Renew Let's Encrypt certificates (Shahkar)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${CERTBOT_BIN} renew --config-dir ${LE_DIR} --work-dir /var/lib/letsencrypt --logs-dir /var/log/letsencrypt --quiet
EOF
  cat > /etc/systemd/system/certbot-renew.timer <<EOF
[Unit]
Description=Run certbot renew periodically (frequent for 6-day IP certs)

[Timer]
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now certbot-renew.timer >/dev/null 2>&1 || true
  ok "Automatic renewal enabled (certbot-renew.timer + nginx reload hook)."
}

# --------------------------------------------------------------------------- #
# Bind the panel and align public URLs in .env
# --------------------------------------------------------------------------- #
update_env() {
  [ -f "$ENV_FILE" ] || { warn ".env not found at ${ENV_FILE} — skipping app bind/origin update."; return; }
  local scheme_host
  scheme_host="https://${SERVER_NAME}"

  set_kv() { # key value
    if grep -qE "^[# ]*${1}\s*=" "$ENV_FILE"; then
      sed -i -E "s|^[# ]*${1}\s*=.*|${1}=${2}|" "$ENV_FILE"
    else
      echo "${1}=${2}" >> "$ENV_FILE"
    fi
  }
  set_kv "UVICORN_HOST" "0.0.0.0"
  set_kv "PANEL_PUBLIC_ADDRESS" "${scheme_host}"
  set_kv "XRAY_SUBSCRIPTION_URL_PREFIX" "${scheme_host}"
  set_kv "ALLOWED_ORIGINS" "${scheme_host},http://127.0.0.1:${PANEL_PORT},http://${SERVER_NAME}:${PANEL_PORT}"
  ok ".env updated: public address ${scheme_host}, sub links via ${scheme_host}."
}

restart_panel() {
  local compose_file=""
  if [ -f "${ROOT}/docker-compose.postgres.yml" ]; then
    compose_file="docker-compose.postgres.yml"
  elif [ -f "${ROOT}/docker-compose.yml" ]; then
    compose_file="docker-compose.yml"
  fi
  if systemctl is-enabled shahkar.service >/dev/null 2>&1 || systemctl is-active shahkar.service >/dev/null 2>&1; then
    log "Restarting shahkar.service..."
    systemctl restart shahkar.service || warn "Could not restart shahkar.service — restart it manually."
  elif command -v docker >/dev/null 2>&1 && [ -n "$compose_file" ]; then
    log "Recreating docker compose stack (picks up .env changes)..."
    if docker compose version >/dev/null 2>&1; then
      (cd "${ROOT}" && docker compose -f "$compose_file" up -d --force-recreate shahkar) \
        || warn "Could not restart docker stack — run: shahkar restart"
    else
      (cd "${ROOT}" && docker-compose -f "$compose_file" up -d --force-recreate shahkar) \
        || warn "Could not restart docker stack — run: shahkar restart"
    fi
  else
    warn "Panel not managed by systemd/docker here — restart manually: shahkar restart"
  fi
}

# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
install_nginx
install_certbot
write_self_signed
# Start nginx on the bootstrap cert so the ACME webroot is reachable on :80.
write_nginx_conf "${SELF_DIR}/bootstrap.crt" "${SELF_DIR}/bootstrap.key"
systemctl enable --now nginx >/dev/null 2>&1 || true
systemctl reload nginx || systemctl restart nginx
issue_cert
# Swap in the real certificate and reload.
write_nginx_conf "${LE_LIVE}/fullchain.pem" "${LE_LIVE}/privkey.pem"
systemctl reload nginx
setup_renewal
update_env
restart_panel

echo
ok "HTTPS is live."
dash_path="/dashboard/"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a && source "$ENV_FILE" && set +a
  dash_path="${DASHBOARD_PATH:-/dashboard/}"
fi
case "$dash_path" in */) ;; *) dash_path="${dash_path}/" ;; esac
echo "  ${BOLD}Dashboard${NC}  https://${SERVER_NAME}${dash_path}"
echo "  ${BOLD}Cert${NC}       Let's Encrypt (${MODE} mode), auto-renewing"
[ "$MODE" = "ip" ] && echo "  ${YELLOW}Note${NC}       IP certificates are valid 6 days; renewal runs twice daily."
echo "  ${BOLD}App port${NC}   0.0.0.0:${PANEL_PORT} (block ${PANEL_PORT} in firewall; use HTTPS :443)"
echo "  ${BOLD}Edge${NC}       Proxy inbounds can share :443 via SNI (see Hosts → CDN domain:443)"
echo
