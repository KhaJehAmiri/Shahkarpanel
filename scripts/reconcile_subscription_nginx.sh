#!/usr/bin/env bash
# Apply NexusPanel legacy subscription nginx configs from
# /var/lib/nexuspanel/edge/subscription/desired.json
#
# Usage:
#   sudo scripts/reconcile_subscription_nginx.sh --apply
#   sudo scripts/reconcile_subscription_nginx.sh --dry-run
#   sudo scripts/reconcile_subscription_nginx.sh --reload-only
set -euo pipefail

EDGE_DIR="${NEXUSPANEL_EDGE_DIR:-/var/lib/nexuspanel/edge}"
DESIRED="${EDGE_DIR}/subscription/desired.json"
STAGING="${EDGE_DIR}/subscription/nginx/sites"
NGINX_AVAILABLE="${NGINX_AVAILABLE:-/etc/nginx/sites-available}"
NGINX_ENABLED="${NGINX_ENABLED:-/etc/nginx/sites-enabled}"
WEBROOT="${NEXUSPANEL_ACME_WEBROOT:-/var/www/letsencrypt}"
CERTBOT="${CERTBOT:-/opt/certbot-venv/bin/certbot}"
APPLY=0
DRY_RUN=0
RELOAD_ONLY=0

RED=$'\e[31m'; GREEN=$'\e[32m'; BLUE=$'\e[34m'; YELLOW=$'\e[33m'; NC=$'\e[0m'
log() { echo "${BLUE}[sub-nginx]${NC} $*"; }
ok() { echo "${GREEN}[sub-nginx]${NC} $*"; }
warn() { echo "${YELLOW}[sub-nginx]${NC} $*"; }
die() { echo "${RED}[sub-nginx]${NC} $*" >&2; exit 1; }

reload_nginx() {
  nginx -t || return 1
  # Prefer signal reload — works inside chroot helpers where systemctl/dbus
  # is unavailable (otherwise new SNI certs stay invisible until manual restart).
  if [ -f /run/nginx.pid ]; then
    kill -HUP "$(cat /run/nginx.pid)" 2>/dev/null && return 0
  fi
  if [ -f /var/run/nginx.pid ]; then
    kill -HUP "$(cat /var/run/nginx.pid)" 2>/dev/null && return 0
  fi
  nginx -s reload 2>/dev/null && return 0
  systemctl reload nginx 2>/dev/null && return 0
  warn "nginx reload skipped"
  return 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    --reload-only) RELOAD_ONLY=1; shift;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0;;
    *) die "Unknown arg: $1";;
  esac
done

if [ "$RELOAD_ONLY" -eq 1 ]; then
  [ "$(id -u)" -eq 0 ] || die "Run as root for --reload-only (sudo)."
  command -v nginx >/dev/null 2>&1 || die "nginx not installed."
  reload_nginx || die "nginx -t/reload failed"
  ok "nginx reloaded"
  exit 0
fi

[ -f "$DESIRED" ] || { log "No desired state ($DESIRED) — nothing to reconcile."; exit 0; }

if [ "$APPLY" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  APPLY=1
fi

if [ "$APPLY" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
  die "Run as root for --apply (sudo)."
fi

command -v nginx >/dev/null 2>&1 || die "nginx not installed."
[ -d "$NGINX_AVAILABLE" ] || die "Missing $NGINX_AVAILABLE"
[ -d "$NGINX_ENABLED" ] || die "Missing $NGINX_ENABLED"
[ -d "$STAGING" ] || die "Missing staging dir $STAGING"

mkdir -p "$WEBROOT"
chmod -R a+rX "$WEBROOT" 2>/dev/null || true

if [ ! -x "$CERTBOT" ]; then
  CERTBOT="$(command -v certbot || true)"
fi

DOMAINS=$(python3 - "$DESIRED" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
seen = []
for d in data.get("domains") or []:
    d = (d or "").strip()
    if d and d not in seen:
        seen.append(d)
print("\n".join(seen))
PY
)

issue_cert() {
  local domain="$1"
  [ -n "$domain" ] || return 0
  if [ -f "/etc/letsencrypt/live/${domain}/fullchain.pem" ]; then
    return 0
  fi
  [ -n "$CERTBOT" ] && [ -x "$CERTBOT" ] || {
    warn "certbot missing — create cert for ${domain} manually."
    return 1
  }
  log "Requesting Let's Encrypt certificate for ${domain}..."
  "$CERTBOT" certonly --webroot -w "$WEBROOT" -d "$domain" \
    --agree-tos --non-interactive --register-unsafely-without-email \
    || return 1
  ok "Certificate issued for ${domain}"
}

# Remove stale subscription symlinks only (never touch panel or CDN vhosts).
for link in "$NGINX_ENABLED"/nexuspanel-sub-*; do
  [ -e "$link" ] || continue
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Would remove stale $link"
  else
    rm -f "$link"
  fi
done

for conf in "$STAGING"/*.conf; do
  [ -f "$conf" ] || continue
  base=$(basename "$conf" .conf)
  dest="${NGINX_AVAILABLE}/${base}.conf"
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Would install $conf → $dest"
    log "Would enable ${NGINX_ENABLED}/${base}.conf"
  else
    cp "$conf" "$dest"
    ln -sf "$dest" "${NGINX_ENABLED}/${base}.conf"
    ok "Installed ${base}.conf"
  fi
done

if [ "$DRY_RUN" -eq 1 ]; then
  log "Dry run complete."
  exit 0
fi

# Letsencrypt live/archive are often 0700; panel process (non-root) must be
# able to detect certs for redirects / Enable SSL status.
relax_le_perms() {
  local domain="$1"
  chmod 755 /etc/letsencrypt/live /etc/letsencrypt/archive 2>/dev/null || true
  if [ -n "$domain" ] && [ -d "/etc/letsencrypt/live/${domain}" ]; then
    chmod 755 "/etc/letsencrypt/live/${domain}" "/etc/letsencrypt/archive/${domain}" 2>/dev/null || true
    chmod 644 "/etc/letsencrypt/archive/${domain}"/fullchain*.pem \
      "/etc/letsencrypt/archive/${domain}"/cert*.pem \
      "/etc/letsencrypt/archive/${domain}"/chain*.pem 2>/dev/null || true
  fi
}

reload_nginx || die "nginx -t/reload failed (install ACME vhosts first, then retry cert issuance)"

while IFS= read -r domain; do
  [ -n "$domain" ] || continue
  if issue_cert "$domain"; then
    relax_le_perms "$domain"
  else
    warn "Cert for ${domain} not ready — HTTPS on sub port pending."
  fi
done <<< "$DOMAINS"

# Panel container may not see /etc/letsencrypt when syncing; ensure each
# subscription domain with a live cert also has a :443 panel vhost (SNI).
ensure_https_vhost() {
  local domain="$1"
  local safe base dest conf
  [ -f "/etc/letsencrypt/live/${domain}/fullchain.pem" ] || return 0
  [ -f "/etc/letsencrypt/live/${domain}/privkey.pem" ] || return 0
  safe=$(echo "$domain" | tr -c 'A-Za-z0-9._-' '-' | sed 's/^-*//;s/-*$//')
  [ -n "$safe" ] || return 0
  base="nexuspanel-sub-https-${safe}"
  conf="${STAGING}/${base}.conf"
  dest="${NGINX_AVAILABLE}/${base}.conf"
  cat > "$conf" <<NGINX
# Subscription domain HTTPS (443) — managed by NexusPanel
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${domain};

    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    client_max_body_size 200m;

    error_page 502 503 504 = @panel_restarting;

    location @panel_restarting {
        default_type text/html;
        charset utf-8;
        add_header Cache-Control "no-store" always;
        add_header Retry-After "2" always;
        root /var/lib/nexuspanel/nginx/html;
        rewrite ^ /restarting.html break;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 1s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_next_upstream off;
    }
}
NGINX
  cp "$conf" "$dest"
  ln -sf "$dest" "${NGINX_ENABLED}/${base}.conf"
  ok "Ensured ${base}.conf for ${domain}"
}

HTTPS_TOUCHED=0
while IFS= read -r domain; do
  [ -n "$domain" ] || continue
  if [ -f "/etc/letsencrypt/live/${domain}/fullchain.pem" ]; then
    ensure_https_vhost "$domain"
    HTTPS_TOUCHED=1
  fi
done <<< "$DOMAINS"

if [ "$HTTPS_TOUCHED" -eq 1 ]; then
  reload_nginx || die "nginx -t/reload failed after HTTPS vhost ensure"
fi

# Always reload once more after cert/vhost changes. A prior HUP (before certbot)
# is not enough — new SNI server_names (e.g. srw4 after panel migration) stay
# on the default cert until workers pick up the final config.
reload_nginx || die "nginx -t/reload failed on final pass"
ok "subscription legacy nginx reloaded"
