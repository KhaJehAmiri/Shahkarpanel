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
  mkdir -p /var/lib/nexuspanel/nginx/html
  chmod -R a+rX /var/lib/nexuspanel/nginx 2>/dev/null || true
  if [ -d /code/.git ]; then
    chown -R nexuspanel:nexuspanel /code 2>/dev/null || true
  elif [ -f /code/.env ]; then
    chown nexuspanel:nexuspanel /code/.env 2>/dev/null || true
    chmod 600 /code/.env 2>/dev/null || true
  fi
}

# Skip full ``alembic upgrade`` when already at head — cold upgrade takes ~6s+
# even as a no-op and delays :8000 coming back after docker restart.
# Compare DB stamp to ``ALEMBIC_HEAD`` (no Alembic ScriptDirectory import).
run_migrations_if_needed() {
  cd /code
  if python - <<'PY'
import os
import sys
from pathlib import Path

def db_url() -> str:
    url = os.environ.get("SQLALCHEMY_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
    if url:
        return url
    for path in (Path("/var/lib/nexuspanel/.env"), Path("/code/.env")):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() in ("SQLALCHEMY_DATABASE_URL", "DATABASE_URL"):
                return v.strip().strip("'").strip('"')
    return ""

try:
    head = Path("/code/ALEMBIC_HEAD").read_text(encoding="utf-8").strip().splitlines()[0].strip()
    url = db_url()
    if not head or not url:
        sys.exit(1)
    from sqlalchemy import create_engine, text
    eng = create_engine(url)
    with eng.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
    if row and row[0] == head:
        sys.exit(0)
except Exception:
    sys.exit(1)
sys.exit(2)
PY
  then
    echo "alembic: already at head — skip upgrade"
    return 0
  fi
  echo "alembic: applying migrations…"
  alembic upgrade head
  # Keep ALEMBIC_HEAD in sync after a successful upgrade (best-effort).
  python - <<'PY' >/dev/null 2>&1 || true
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
if head:
    Path("/code/ALEMBIC_HEAD").write_text(head + "\n", encoding="utf-8")
PY
}

# ``runuser`` drops all supplementary groups and rebuilds the group list purely
# from nexuspanel's own /etc/group membership (initgroups), so compose's
# ``group_add: [DOCKER_GID]`` — granted only to this root entrypoint process —
# never reaches the unprivileged app process. Without docker.sock access the
# app's own privileged-kill escalation (root-owned stray Xray from an
# out-of-band ``docker exec`` session) silently no-ops, and a single orphaned
# root Xray process can wedge the health-check into an endless bind-reclaim
# restart storm. Make the membership permanent so every future container
# start (not just this fix) has it.
fix_docker_socket_group() {
  local sock_gid=""
  sock_gid="${DOCKER_GID:-}"
  if [ -z "$sock_gid" ] && [ -S /var/run/docker.sock ]; then
    sock_gid="$(stat -c '%g' /var/run/docker.sock 2>/dev/null)" || sock_gid=""
  fi
  [ -n "$sock_gid" ] || return 0
  local grp_name=""
  grp_name="$(getent group "$sock_gid" 2>/dev/null | cut -d: -f1)" || grp_name=""
  if [ -z "$grp_name" ]; then
    groupadd -g "$sock_gid" dockerhost 2>/dev/null || true
    grp_name="dockerhost"
  fi
  usermod -aG "$grp_name" nexuspanel 2>/dev/null || true
  return 0
}

start_panel_process() {
  cd /code
  run_migrations_if_needed
  exec python main.py
}

if [ "$(id -u)" -eq 0 ]; then
  fix_runtime_permissions
  fix_docker_socket_group || true
  # BBR + TCP/UDP buffer tuning on the host (--network=host); best-effort, idempotent.
  if [ -d /code ]; then
    eval "$(cd /code && python3 -c 'from app.xray.network_defaults import host_network_tuning_shell; print(host_network_tuning_shell())')" \
      >/dev/null 2>&1 || true
  fi
  if [ "${1:-panel}" = "panel" ]; then
    # Re-enter this script as nexuspanel so migrate+main share one code path.
    exec runuser -u nexuspanel -- bash /code/docker-entrypoint.sh panel
  fi
  exec runuser -u nexuspanel -- "$@"
fi

if [ "${1:-panel}" = "panel" ]; then
  start_panel_process
fi
exec "$@"
