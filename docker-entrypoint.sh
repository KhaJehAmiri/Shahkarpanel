#!/bin/bash
set -euo pipefail

fix_runtime_permissions() {
  if [ -f /var/lib/nexuspanel/.env ]; then
    chown nexuspanel:nexuspanel /var/lib/nexuspanel/.env 2>/dev/null || true
    chmod 600 /var/lib/nexuspanel/.env 2>/dev/null || true
  fi
  if [ -f /var/lib/nexuspanel/xray_config.json ]; then
    chown nexuspanel:nexuspanel /var/lib/nexuspanel/xray_config.json 2>/dev/null || true
    chmod 664 /var/lib/nexuspanel/xray_config.json 2>/dev/null || true
  fi
  if [ -f /var/lib/nexuspanel/install-meta.json ]; then
    chown nexuspanel:nexuspanel /var/lib/nexuspanel/install-meta.json 2>/dev/null || true
    chmod 664 /var/lib/nexuspanel/install-meta.json 2>/dev/null || true
  fi
  mkdir -p /var/lib/nexuspanel/backups
  chown -R nexuspanel:nexuspanel /var/lib/nexuspanel/backups 2>/dev/null || true
  mkdir -p /var/lib/nexuspanel/backups/migrations
  chown -R nexuspanel:nexuspanel /var/lib/nexuspanel/backups/migrations 2>/dev/null || true
  mkdir -p /var/lib/nexuspanel/migrations
  chown -R nexuspanel:nexuspanel /var/lib/nexuspanel/migrations 2>/dev/null || true
  mkdir -p /var/lib/nexuspanel/xray-tls
  chown -R nexuspanel:nexuspanel /var/lib/nexuspanel/xray-tls 2>/dev/null || true
  chmod 750 /var/lib/nexuspanel/xray-tls 2>/dev/null || true
  mkdir -p /var/lib/nexuspanel/xray-config-history
  chown -R nexuspanel:nexuspanel /var/lib/nexuspanel/xray-config-history 2>/dev/null || true
  mkdir -p /var/lib/nexuspanel/edge/nginx/sites
  chown -R nexuspanel:nexuspanel /var/lib/nexuspanel/edge 2>/dev/null || true
  chmod -R u+rwX,g+rwX /var/lib/nexuspanel/edge 2>/dev/null || true
  if [ -d /code/.git ]; then
    chown -R nexuspanel:nexuspanel /code 2>/dev/null || true
  elif [ -f /code/.env ]; then
    chown nexuspanel:nexuspanel /code/.env 2>/dev/null || true
    chmod 600 /code/.env 2>/dev/null || true
  fi
}

run_panel() {
  exec runuser -u nexuspanel -- bash -c 'cd /code && alembic upgrade head && exec python main.py'
}

if [ "$(id -u)" -eq 0 ]; then
  fix_runtime_permissions
  # BBR + TCP/UDP buffer tuning on the host (--network=host); best-effort, idempotent.
  if [ -d /code ]; then
    eval "$(cd /code && python3 -c 'from app.xray.network_defaults import host_network_tuning_shell; print(host_network_tuning_shell())')" \
      >/dev/null 2>&1 || true
  fi
  if [ "${1:-panel}" = "panel" ]; then
    run_panel
  fi
  exec runuser -u nexuspanel -- "$@"
fi

if [ "${1:-panel}" = "panel" ]; then
  cd /code
  exec bash -c 'alembic upgrade head && exec python main.py'
fi
exec "$@"
