#!/bin/bash
# Install (or refresh) the shahkar systemd unit for a non-Docker deployment.
# The panel binds to 127.0.0.1 (see .env UVICORN_HOST); put nginx in front for
# TLS with: sudo scripts/setup_https.sh
set -euo pipefail

SERVICE_NAME="shahkar"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON_BIN="$(command -v python3 || echo /usr/bin/python3)"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Shahkar
Documentation=https://github.com/KhaJehAmiri/Shahkarpanel
Wants=network-online.target
After=network-online.target nss-lookup.target
# Never give up restarting: a proxy panel must stay up.
StartLimitIntervalSec=0

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${PYTHON_BIN} ${APP_DIR}/main.py
# Recover from ANY exit (crash, OOM, or even a clean shutdown).
Restart=always
RestartSec=5
# Reap child Xray core(s) with the panel so no orphan survives.
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "Service file written: ${SERVICE_FILE}"
echo "Enable + start with: systemctl enable --now ${SERVICE_NAME}.service"
