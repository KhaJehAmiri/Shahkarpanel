#!/usr/bin/env bash
# Apply NexusPanel legacy subscription nginx configs from
# /var/lib/nexuspanel/edge/subscription/desired.json
#
# Usage:
#   sudo scripts/reconcile_subscription_nginx.sh --apply
#   sudo scripts/reconcile_subscription_nginx.sh --dry-run
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

RED=$'\e[31m'; GREEN=$'\e[32m'; BLUE=$'\e[34m'; YELLOW=$'\e[33m'; NC=$'\e[0m'
log() { echo "${BLUE}[sub-nginx]${NC} $*"; }
ok() { echo "${GREEN}[sub-nginx]${NC} $*"; }
warn() { echo "${YELLOW}[sub-nginx]${NC} $*"; }
die() { echo "${RED}[sub-nginx]${NC} $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help)
      sed -n '2,10p' "$0"; exit 0;;
    *) die "Unknown arg: $1";;
  esac
done

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

nginx -t || die "nginx -t failed (install ACME vhosts first, then retry cert issuance)"
if systemctl reload nginx 2>/dev/null; then
  :
elif nginx -s reload 2>/dev/null; then
  :
elif [ -f /run/nginx.pid ]; then
  kill -HUP "$(cat /run/nginx.pid)" 2>/dev/null || warn "nginx reload skipped"
else
  warn "nginx reload skipped"
fi

while IFS= read -r domain; do
  [ -n "$domain" ] || continue
  issue_cert "$domain" || warn "Cert for ${domain} not ready — HTTPS on sub port pending."
done <<< "$DOMAINS"

ok "subscription legacy nginx reloaded"
