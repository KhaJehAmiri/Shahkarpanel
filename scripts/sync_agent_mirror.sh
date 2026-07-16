#!/usr/bin/env bash
# Sync the panel's cached node-agent docker-save tarball to the Iran HTTP mirror.
#
# Usage:
#   NODE_AGENT_MIRROR_SSH=root@37.32.40.55 \
#   NODE_AGENT_MIRROR_SSH_PASS=... \
#   bash scripts/sync_agent_mirror.sh
#
# Or with an existing SSH key (no password):
#   NODE_AGENT_MIRROR_SSH=root@37.32.40.55 bash scripts/sync_agent_mirror.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/nexuspanel}"
CACHE_DIR="${CACHE_DIR:-/var/lib/nexuspanel/cache/agent-images}"
REMOTE="${NODE_AGENT_MIRROR_SSH:-}"
REMOTE_PATH="${NODE_AGENT_MIRROR_REMOTE_PATH:-/var/www/nexuspanel/node-agent-image.tar.gz}"
IMAGE="${NODE_AGENT_IMAGE:-nexuspanel/node:latest}"

if [ -z "$REMOTE" ]; then
  echo "NODE_AGENT_MIRROR_SSH not set — skip mirror sync."
  exit 0
fi

# Ensure a fresh cache exists on the panel.
if [ -f "${APP_DIR}/app/provisioning/agent_image.py" ]; then
  python3 - <<PY
import sys
sys.path.insert(0, "${APP_DIR}")
from app.provisioning.agent_image import cached_image_path
print(cached_image_path("${IMAGE}"))
PY
fi

SRC="$(ls -t "${CACHE_DIR}"/*.tar.gz 2>/dev/null | head -1 || true)"
if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
  echo "No agent-image tarball in ${CACHE_DIR}; building via docker save…"
  mkdir -p "${CACHE_DIR}"
  SRC="${CACHE_DIR}/manual-sync.tar.gz"
  docker save "${IMAGE}" | gzip -c > "${SRC}"
fi

echo "Syncing $(du -h "$SRC" | awk '{print $1}') → ${REMOTE}:${REMOTE_PATH}"

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
if [ -n "${NODE_AGENT_MIRROR_SSH_PASS:-}" ] && command -v sshpass >/dev/null 2>&1; then
  export SSHPASS="${NODE_AGENT_MIRROR_SSH_PASS}"
  sshpass -e ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p $(dirname "$REMOTE_PATH")"
  sshpass -e scp "${SSH_OPTS[@]}" "$SRC" "${REMOTE}:${REMOTE_PATH}.partial"
  sshpass -e ssh "${SSH_OPTS[@]}" "$REMOTE" "mv -f '${REMOTE_PATH}.partial' '${REMOTE_PATH}' && chmod 644 '${REMOTE_PATH}'"
else
  ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p $(dirname "$REMOTE_PATH")"
  scp "${SSH_OPTS[@]}" "$SRC" "${REMOTE}:${REMOTE_PATH}.partial"
  ssh "${SSH_OPTS[@]}" "$REMOTE" "mv -f '${REMOTE_PATH}.partial' '${REMOTE_PATH}' && chmod 644 '${REMOTE_PATH}'"
fi

echo "Mirror sync OK: http://$(echo "$REMOTE" | sed 's/.*@//')/nexuspanel/node-agent-image.tar.gz"
