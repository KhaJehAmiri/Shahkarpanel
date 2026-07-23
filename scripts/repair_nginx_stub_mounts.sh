#!/usr/bin/env bash
# Repair Docker bind-mount stub directories that break host nginx.
#
# When compose mounts a missing *file* path (e.g. /etc/nginx/nginx.conf or
# /run/nginx.pid), Docker creates a directory on the host. That leaves nginx
# unable to start, so reseller subscription domains never listen.
#
# Usage: sudo scripts/repair_nginx_stub_mounts.sh
set -euo pipefail

RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'; NC=$'\e[0m'
log() { echo "${BLUE}[nginx-repair]${NC} $*"; }
ok() { echo "${GREEN}[nginx-repair]${NC} $*"; }
warn() { echo "${YELLOW}[nginx-repair]${NC} $*"; }

[ "$(id -u)" -eq 0 ] || { echo "${RED}[nginx-repair]${NC} Run as root." >&2; exit 1; }

ts="$(date +%Y%m%d%H%M%S)"
repaired=0

repair_file_from_dpkg_new() {
  local path="$1"
  local dpkg_new="${path}.dpkg-new"
  if [ -d "$path" ]; then
    warn "stub directory at ${path} — moving aside"
    mv "$path" "${path}.broken-dir.${ts}"
    repaired=1
  fi
  if [ ! -e "$path" ] && [ -f "$dpkg_new" ]; then
    cp -a "$dpkg_new" "$path"
    ok "restored ${path} from ${dpkg_new}"
    repaired=1
  fi
}

# File paths that must never be directories.
repair_file_from_dpkg_new /etc/nginx/nginx.conf
repair_file_from_dpkg_new /etc/nginx/mime.types
repair_file_from_dpkg_new /etc/nginx/proxy_params

for pid in /run/nginx.pid /var/run/nginx.pid; do
  if [ -d "$pid" ]; then
    warn "stub directory at ${pid} — removing"
    rm -rf "$pid"
    repaired=1
  fi
done

if [ -d /usr/sbin/nginx ]; then
  warn "stub directory at /usr/sbin/nginx — removing (reinstall nginx package if needed)"
  rm -rf /usr/sbin/nginx
  repaired=1
fi

if [ "$repaired" -eq 0 ]; then
  ok "no nginx stub mounts found"
  exit 0
fi

if command -v nginx >/dev/null 2>&1 && [ -f /etc/nginx/nginx.conf ]; then
  if nginx -t 2>/dev/null; then
    systemctl enable nginx >/dev/null 2>&1 || true
    systemctl restart nginx >/dev/null 2>&1 || systemctl start nginx >/dev/null 2>&1 || true
    if systemctl is-active --quiet nginx 2>/dev/null; then
      ok "nginx is active"
    else
      warn "nginx still not active — run: apt-get install --reinstall nginx && nexuspanel https"
    fi
  else
    warn "nginx -t failed after repair — check /etc/nginx"
  fi
else
  warn "nginx binary/config missing — install with: apt-get install -y nginx && nexuspanel https"
fi
