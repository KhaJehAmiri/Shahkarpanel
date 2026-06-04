#!/usr/bin/env bash
# Restart NexusPanel outside Docker when compose/systemd is unavailable.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="${NEXUS_PANEL_LOG:-/tmp/nexuspanel.log}"

pkill -f "python3 main.py" 2>/dev/null || true
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
