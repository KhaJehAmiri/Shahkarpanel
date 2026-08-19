#!/bin/bash
set -euo pipefail

# Resolve panel unix user by name, else by uid 1000 (image may still use an older username).
if id shahkar >/dev/null 2>&1; then
  PANEL_USER=shahkar
else
  PANEL_USER="$(getent passwd 1000 2>/dev/null | cut -d: -f1 || true)"
  if [ -z "${PANEL_USER}" ]; then
    PANEL_USER=1000
  fi
fi
PANEL_GROUP="$PANEL_USER"

# Compatibility for configs that still reference the old data path


fix_runtime_permissions() {
  if [ -f /var/lib/shahkar/.env ]; then
    chown "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/.env 2>/dev/null || true
    chmod 600 /var/lib/shahkar/.env 2>/dev/null || true
  fi
  if [ -f /var/lib/shahkar/xray_config.json ]; then
    chown "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/xray_config.json 2>/dev/null || true
    chmod 664 /var/lib/shahkar/xray_config.json 2>/dev/null || true
  fi
  if [ -f /var/lib/shahkar/install-meta.json ]; then
    chown "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/install-meta.json 2>/dev/null || true
    chmod 664 /var/lib/shahkar/install-meta.json 2>/dev/null || true
  fi
  # Worker heartbeat / wake files: data dir is 755 root, so the unprivileged
  # process cannot create them. Pre-create so healthcheck and file fallback work.
  touch /var/lib/shahkar/worker.heartbeat /var/lib/shahkar/worker.wake 2>/dev/null || true
  chown "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/worker.heartbeat /var/lib/shahkar/worker.wake 2>/dev/null || true
  chmod 664 /var/lib/shahkar/worker.heartbeat /var/lib/shahkar/worker.wake 2>/dev/null || true
  mkdir -p /var/lib/shahkar/backups
  chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/backups 2>/dev/null || true
  mkdir -p /var/lib/shahkar/backups/migrations
  chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/backups/migrations 2>/dev/null || true
  mkdir -p /var/lib/shahkar/migrations
  chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/migrations 2>/dev/null || true
  mkdir -p /var/lib/shahkar/payment_receipts
  chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/payment_receipts 2>/dev/null || true
  mkdir -p /var/lib/shahkar/xray-tls
  chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/xray-tls 2>/dev/null || true
  chmod 750 /var/lib/shahkar/xray-tls 2>/dev/null || true
  mkdir -p /var/lib/shahkar/xray-config-history
  chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/xray-config-history 2>/dev/null || true
  mkdir -p /var/lib/shahkar/edge/nginx/sites
  chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/edge 2>/dev/null || true
  chmod -R u+rwX,g+rwX /var/lib/shahkar/edge 2>/dev/null || true
  mkdir -p /var/lib/shahkar/nginx/html
  chmod -R a+rX /var/lib/shahkar/nginx 2>/dev/null || true
  # Node SSH secrets (control-tunnel key/password fallback, app/provisioning/node_ssh.py).
  # These are frequently created/rotated by root (host SSH sessions, setup scripts run
  # as root) while the panel process itself runs as shahkar (runuser below) — an
  # owner mismatch here silently disables the SSH control-tunnel fallback (permission
  # denied is swallowed by a broad except-Exception in has_ssh_for_host), which then
  # looks like a flaky node connection instead of a config problem. Reclaim ownership
  # on every boot so this never depends on which user created the files.
  if [ -d /var/lib/shahkar/secrets ]; then
    chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/secrets 2>/dev/null || true
    chmod 700 /var/lib/shahkar/secrets 2>/dev/null || true
    find /var/lib/shahkar/secrets -maxdepth 1 -type f -exec chmod 600 {} + 2>/dev/null || true
  fi
  # Never `chown -R /code`. On a bind-mounted git checkout that walks tens of
  # thousands of files on every container start and is what pegs CPU while the
  # worker crash-loops after OOM. The process only needs to own its data dir
  # (handled above) and optionally the env file.
  if [ -f /code/.env ]; then
    chown "$PANEL_USER:$PANEL_GROUP" /code/.env 2>/dev/null || true
    chmod 600 /code/.env 2>/dev/null || true
  fi
  # In-panel Xray upgrade/downgrade runs as shahkar (not root).
  # /usr/local/bin is not writable for that user, so keep a private copy under
  # /var/lib/shahkar/bin (see app/utils/xray_upgrade.py fallback paths).
  mkdir -p /var/lib/shahkar/bin /var/lib/shahkar/share/xray
  if [ -x /usr/local/bin/xray ] && [ ! -x /var/lib/shahkar/bin/xray ]; then
    cp -f /usr/local/bin/xray /var/lib/shahkar/bin/xray 2>/dev/null || true
    chmod 755 /var/lib/shahkar/bin/xray 2>/dev/null || true
  fi
  if [ -d /usr/local/share/xray ]; then
    for dat in /usr/local/share/xray/*.dat; do
      [ -f "$dat" ] || continue
      base="$(basename "$dat")"
      if [ ! -f "/var/lib/shahkar/share/xray/$base" ]; then
        cp -f "$dat" "/var/lib/shahkar/share/xray/$base" 2>/dev/null || true
      fi
    done
  fi
  chown -R "$PANEL_USER:$PANEL_GROUP" /var/lib/shahkar/bin /var/lib/shahkar/share/xray 2>/dev/null || true
}

# Skip full ``alembic upgrade`` when already at head — cold upgrade takes ~6s+
# even as a no-op and delays :8000 coming back after docker restart.
# Compare DB stamp to ``ALEMBIC_HEAD`` (no Alembic ScriptDirectory import).
run_migrations_if_needed() {
  cd /code
  # Quarantine leftover ``b-*.py`` / copy-of revision files *before* Alembic
  # builds ScriptDirectory — a duplicate revision id exits 255 and docker
  # restart-loops the panel.
  python /code/app/db/migrations/guard_revisions.py /code/app/db/migrations/versions \
    || { echo "alembic: revision guard failed"; exit 1; }
  if python - <<'PY'
import os
import sys
from pathlib import Path

def db_url() -> str:
    url = os.environ.get("SQLALCHEMY_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
    if url:
        return url
    for path in (Path("/var/lib/shahkar/.env"), Path("/code/.env")):
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
# from shahkar's own /etc/group membership (initgroups), so compose's
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
  # Use resolved PANEL_USER (shahkar on new images, shahkar on older ones).
  # Hardcoding ``shahkar`` silently no-ops on legacy images → app loses docker.sock
  # after runuser rebuilds groups from /etc/group, and branding domain reconcile fails.
  usermod -aG "$grp_name" "$PANEL_USER" 2>/dev/null || true
  # Best-effort for whichever alias exists in this image.
  for _u in shahkar; do
    if [ "$_u" != "$PANEL_USER" ] && id "$_u" >/dev/null 2>&1; then
      usermod -aG "$grp_name" "$_u" 2>/dev/null || true
    fi
  done
  return 0
}

start_panel_process() {
  cd /code
  run_migrations_if_needed
  # Soft nofile often stays 1024 even when compose raises the hard limit
  # (runuser). Without this, RPyC/node sessions hit Errno 24 and mark nodes error.
  ulimit -n 1048576 2>/dev/null || ulimit -n 65536 2>/dev/null || true
  exec python main.py
}

start_worker_process() {
  cd /code
  # Migrations run in the API container first (worker depends_on healthy).
  ulimit -n 1048576 2>/dev/null || ulimit -n 65536 2>/dev/null || true
  exec python -m app.worker
}

if [ "$(id -u)" -eq 0 ]; then
  fix_runtime_permissions
  fix_docker_socket_group || true
  # BBR + TCP/UDP buffer tuning on the host (--network=host); best-effort.
  # Keep this as plain sysctl — do NOT `import app.xray.*` here. That package
  # init constructs XRayCore and used to add ~15-20s of dead time before :8000
  # listened (every restart / in-dashboard update).
  # Keys must stay in sync with app/xray/network_defaults.py HOST_SYSCTL_TUNING.
  sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1 || true
  sysctl -w net.core.rmem_max=26214400 >/dev/null 2>&1 || true
  sysctl -w net.core.wmem_max=26214400 >/dev/null 2>&1 || true
  sysctl -w net.core.netdev_max_backlog=250000 >/dev/null 2>&1 || true
  sysctl -w net.ipv4.udp_mem="65536 131072 262144" >/dev/null 2>&1 || true
  # Persist once (idempotent); avoid rewriting sysctl.conf on every boot.
  if [ -f /etc/sysctl.conf ] && ! grep -q '^net.ipv4.tcp_congestion_control=bbr$' /etc/sysctl.conf 2>/dev/null; then
    {
      echo 'net.ipv4.tcp_congestion_control=bbr'
      echo 'net.core.rmem_max=26214400'
      echo 'net.core.wmem_max=26214400'
      echo 'net.core.netdev_max_backlog=250000'
      echo 'net.ipv4.udp_mem=65536 131072 262144'
    } >> /etc/sysctl.conf 2>/dev/null || true
  fi
  # Host nginx: stock 502 → friendly restarting page (bind-mounted sites-*).
  # Skip when compose created a stub directory for a missing host nginx binary.
  if [ -f /usr/sbin/nginx ] && [ ! -d /usr/sbin/nginx ] \
    && [ -f /code/scripts/ensure_nginx_restarting_page.sh ]; then
    bash /code/scripts/ensure_nginx_restarting_page.sh >>/var/lib/shahkar/ensure-nginx-restarting.log 2>&1 || true
  fi
  if [ "${1:-panel}" = "panel" ]; then
    # Re-enter this script as shahkar so migrate+main share one code path.
    exec runuser -u "$PANEL_USER" -- bash /code/docker-entrypoint.sh panel
  fi
  if [ "${1}" = "worker" ]; then
    exec runuser -u "$PANEL_USER" -- bash /code/docker-entrypoint.sh worker
  fi
  exec runuser -u "$PANEL_USER" -- "$@"
fi

if [ "${1:-panel}" = "panel" ]; then
  start_panel_process
fi
if [ "${1}" = "worker" ]; then
  start_worker_process
fi
exec "$@"
