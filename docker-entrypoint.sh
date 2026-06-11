#!/bin/bash
set -euo pipefail

fix_runtime_permissions() {
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
