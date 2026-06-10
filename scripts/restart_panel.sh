#!/usr/bin/env bash
# Restart NexusPanel outside Docker when compose/systemd is unavailable.
# WARNING: Do not use while nexuspanel.service is active — causes duplicate
# processes on :8000 and orphan Xray. Prefer: systemctl restart nexuspanel.service
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="${NEXUS_PANEL_LOG:-/tmp/nexuspanel.log}"

# Ensure SSH provisioning deps (paramiko) are present.
pip3 install -q -r requirements.txt --break-system-packages 2>/dev/null \
  || pip3 install -q -r requirements.txt 2>/dev/null \
  || true

pkill -f "python3 main.py" 2>/dev/null || true
pkill -f "/opt/nexuspanel/main.py" 2>/dev/null || true
pkill -f "nexuspanel/main.py" 2>/dev/null || true
sleep 2
nohup python3 main.py >>"$LOG" 2>&1 &
disown 2>/dev/null || true
sleep 2
if pgrep -f "python3 main.py" >/dev/null; then
  echo "ok"
  exit 0
fi
echo "failed"
exit 1
