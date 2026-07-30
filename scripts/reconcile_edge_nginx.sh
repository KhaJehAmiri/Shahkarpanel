#!/usr/bin/env bash
# Apply Shahkar edge nginx configs from /var/lib/shahkar/edge/desired.json
#
# Usage:
#   sudo scripts/reconcile_edge_nginx.sh --apply
#   sudo scripts/reconcile_edge_nginx.sh --dry-run
#
# Requires nginx on the host. Panel HTTPS (setup_https.sh) and proxy vhosts share
# :443 via SNI — each server_name gets its own certificate and upstream.
set -euo pipefail

EDGE_DIR="${SHAHKAR_EDGE_DIR:-/var/lib/shahkar/edge}"
DESIRED="${EDGE_DIR}/desired.json"
STAGING="${EDGE_DIR}/nginx/sites"
NGINX_AVAILABLE="${NGINX_AVAILABLE:-/etc/nginx/sites-available}"
NGINX_ENABLED="${NGINX_ENABLED:-/etc/nginx/sites-enabled}"
WEBROOT="${SHAHKAR_ACME_WEBROOT:-/var/www/letsencrypt}"
CERTBOT="${CERTBOT:-/opt/certbot-venv/bin/certbot}"
APPLY=0
DRY_RUN=0

RED=$'\e[31m'; GREEN=$'\e[32m'; BLUE=$'\e[34m'; YELLOW=$'\e[33m'; NC=$'\e[0m'
log() { echo "${BLUE}[edge]${NC} $*"; }
ok() { echo "${GREEN}[edge]${NC} $*"; }
warn() { echo "${YELLOW}[edge]${NC} $*"; }
die() { echo "${RED}[edge]${NC} $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0;;
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

command -v nginx >/dev/null 2>&1 || die "nginx not installed — run scripts/setup_https.sh first."
[ -d "$NGINX_AVAILABLE" ] || die "Missing $NGINX_AVAILABLE"
[ -d "$NGINX_ENABLED" ] || die "Missing $NGINX_ENABLED"

mkdir -p "$WEBROOT" "$STAGING"
chmod -R a+rX "$WEBROOT" 2>/dev/null || true

if [ ! -x "$CERTBOT" ]; then
  CERTBOT="$(command -v certbot || true)"
fi

# Collect unique domains needing certificates
DOMAINS=$(python3 - "$DESIRED" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
data = json.loads(p.read_text())
seen = []
for r in data.get("routes") or []:
    d = (r.get("cert_domain") or r.get("domain") or "").strip()
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
    log "certbot missing — create cert for ${domain} manually or install certbot."
    return 1
  }
  log "Requesting Let's Encrypt certificate for ${domain}..."
  "$CERTBOT" certonly --webroot -w "$WEBROOT" -d "$domain" \
    --agree-tos --non-interactive --register-unsafely-without-email \
    || return 1
  ok "Certificate issued for ${domain}"
}

while IFS= read -r domain; do
  [ -n "$domain" ] || continue
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Would ensure cert for ${domain}"
  else
    issue_cert "$domain" || log "Cert for ${domain} not ready — nginx may fail until DNS/HTTP-01 works."
  fi
done <<< "$DOMAINS"

# Remove stale CDN origin symlinks (panel web vhost is never touched here)
for link in "$NGINX_ENABLED"/shahkar-cdn-* "$NGINX_ENABLED"/shahkar-edge-*; do
  [ -e "$link" ] || continue
  base=$(basename "$link")
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Would remove stale $link"
  else
    rm -f "$link"
  fi
done

# Install staged configs
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

nginx -t || die "nginx -t failed"
if systemctl reload nginx 2>/dev/null; then
  :
elif nginx -s reload 2>/dev/null; then
  :
elif [ -f /run/nginx.pid ]; then
  kill -HUP "$(cat /run/nginx.pid)" 2>/dev/null || warn "nginx reload skipped (run on host: sudo nginx -s reload)"
else
  warn "nginx reload skipped (run on host: sudo scripts/reconcile_edge_nginx.sh --apply)"
fi
ok "nginx reloaded ($(echo "$DOMAINS" | grep -c . || echo 0) edge domain(s))"
