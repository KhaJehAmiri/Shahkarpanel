#!/usr/bin/env bash
#
# NexusPanel installer & manager.
#
# One-line install (run as root):
#   bash <(curl -fsSL https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/scripts/nexuspanel.sh) install
#
# After install, manage with:  nexuspanel <command>
#   install | update | up | down | restart | status | logs
#   backup | restore <file> | cli ... | uninstall
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Config (override via env)
# --------------------------------------------------------------------------- #
APP_NAME="nexuspanel"
APP_DIR="${APP_DIR:-/opt/nexuspanel}"
DATA_DIR="${DATA_DIR:-/var/lib/nexuspanel}"
REPO_URL="${REPO_URL:-https://github.com/KhaJehAmiri/nexuspanel.git}"
REPO_BRANCH="${REPO_BRANCH:-master}"
PANEL_PORT="${PANEL_PORT:-8000}"
SCRIPT_URL="${SCRIPT_URL:-https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/${REPO_BRANCH}/scripts/nexuspanel.sh}"
BIN_PATH="/usr/local/bin/${APP_NAME}"

# Colours
RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'; BOLD=$'\e[1m'; NC=$'\e[0m'

log()  { echo "${BLUE}[*]${NC} $*"; }
ok()   { echo "${GREEN}[✓]${NC} $*"; }
warn() { echo "${YELLOW}[!]${NC} $*"; }
err()  { echo "${RED}[x]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

need_root() {
  [ "$(id -u)" -eq 0 ] || die "Please run as root (sudo)."
}

rand() { head -c "${1:-32}" /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c "${1:-32}"; }

# On small VPS (e.g. 2GB RAM) auto-add swap and skip heavy node-image build.
prepare_low_memory() {
  local ram_mb=4096 swap_mb=0
  if [ -r /proc/meminfo ]; then
    ram_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
    swap_mb=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)
  fi
  if [ "$ram_mb" -lt 3500 ] && [ "$swap_mb" -lt 512 ] && [ ! -f /swapfile ]; then
    log "Low memory (${ram_mb}MB) — creating 2GB swap (one-time)..."
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab 2>/dev/null || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    ok "Swap enabled."
  fi
  if [ "$ram_mb" -lt 3500 ] && [ "${SKIP_NODE_BUILD:-}" != "0" ]; then
    SKIP_NODE_BUILD=1
    log "Low RAM: skipping node-agent build now (optional later)."
  fi
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "${APP_DIR}/docker-compose.yml" "$@"
  else
    docker-compose -f "${APP_DIR}/docker-compose.yml" "$@"
  fi
}

panel_http_code() {
  local path="${1:-/api/setup/status}"
  curl -sf -o /dev/null -w '%{http_code}' --max-time 3 -X GET "http://127.0.0.1:${PANEL_PORT}${path}" 2>/dev/null || echo "000"
}

panel_is_listening() {
  [ "$(panel_http_code /api/setup/status)" = "200" ]
}

# Default Xray inbound ports shipped in xray_config.json (kept in sync with it).
XRAY_INBOUND_PORTS="8443 2095 2096 2097 1080"

# Ensure data dir has required files (safe to run on install and update).
seed_data_dir() {
  mkdir -p "${DATA_DIR}" "${DATA_DIR}/backups"
  local target="${DATA_DIR}/xray_config.json"
  local source="${APP_DIR}/xray_config.json"
  [ -f "${source}" ] || return 0
  if [ ! -f "${target}" ]; then
    cp "${source}" "${target}"
    ok "Created ${target}"
    return 0
  fi
  # Upgrade the legacy single-protocol (Shadowsocks-only) default to the rich
  # multi-protocol template so users get VLESS/VMess/Trojan out of the box.
  if ! grep -q '"vless"' "${target}" && ! grep -q '"vmess"' "${target}"; then
    cp "${target}" "${target}.bak.$(date +%s)"
    cp "${source}" "${target}"
    ok "Upgraded ${target} to multi-protocol (VLESS/VMess/Trojan/Shadowsocks); old config backed up."
  fi
}

# Open panel + Xray inbound ports in UFW when present (never enables inactive
# UFW — avoids SSH lockout).
configure_firewall() {
  command -v ufw >/dev/null 2>&1 || return 0
  log "Configuring firewall (UFW) for panel + inbound ports..."
  ufw allow 22/tcp comment 'SSH' >/dev/null 2>&1 || true
  ufw allow "${PANEL_PORT}/tcp" comment 'NexusPanel' >/dev/null 2>&1 || true
  for p in ${XRAY_INBOUND_PORTS}; do
    ufw allow "${p}" comment 'NexusPanel Xray inbound' >/dev/null 2>&1 || true
  done
  if ufw status 2>/dev/null | grep -qi "Status: active"; then
    ok "UFW: SSH, panel (${PANEL_PORT}) and inbound ports (${XRAY_INBOUND_PORTS}) allowed."
  else
    ok "UFW rules added (firewall not enabled — enable manually if you use UFW)."
  fi
}

# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
install_deps() {
  if ! command -v curl >/dev/null 2>&1; then
    log "Installing curl..."
    (apt-get update -y && apt-get install -y curl) >/dev/null 2>&1 || \
      (yum install -y curl) >/dev/null 2>&1 || true
  fi
  if ! command -v git >/dev/null 2>&1; then
    log "Installing git..."
    (apt-get install -y git) >/dev/null 2>&1 || (yum install -y git) >/dev/null 2>&1 || true
  fi
  if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker >/dev/null 2>&1 || true
    ok "Docker installed."
  fi
}

# --------------------------------------------------------------------------- #
# .env generation (interactive but with sane non-interactive defaults)
# --------------------------------------------------------------------------- #
load_env_creds() {
  local env_file="${APP_DIR}/.env"
  [ -f "$env_file" ] || return 0
  # shellcheck disable=SC1090
  set -a && source "$env_file" && set +a
  ADMIN_USERNAME="${SUDO_USERNAME:-${ADMIN_USERNAME:-}}"
  ADMIN_PASSWORD="${SUDO_PASSWORD:-${ADMIN_PASSWORD:-}}"
  PANEL_PORT="${UVICORN_PORT:-${PANEL_PORT:-8000}}"
  export ADMIN_USERNAME ADMIN_PASSWORD PANEL_PORT
}

write_env() {
  local env_file="${APP_DIR}/.env"
  if [ -f "$env_file" ]; then
    warn ".env already exists; keeping it."
    load_env_creds
    return
  fi

  local admin_user admin_pass
  admin_user="${ADMIN_USERNAME:-admin}"
  admin_pass="${ADMIN_PASSWORD:-$(rand 16)}"

  log "Generating configuration..."
  cat > "$env_file" <<EOF
# Generated by nexuspanel installer on $(date -u +%FT%TZ)
SUDO_USERNAME=${admin_user}
SUDO_PASSWORD=${admin_pass}

UVICORN_HOST=0.0.0.0
UVICORN_PORT=${PANEL_PORT}

SQLALCHEMY_DATABASE_URL=sqlite:////var/lib/nexuspanel/db.sqlite3
XRAY_JSON=/var/lib/nexuspanel/xray_config.json

# Secrets
JWT_SECRET=$(rand 48)
NODE_BOOTSTRAP_TOKEN=$(rand 40)

# Phase 6: address resellers' provisioned nodes use to reach this panel.
PANEL_PUBLIC_ADDRESS=$(curl -fsSL https://api.ipify.org 2>/dev/null || echo "127.0.0.1"):${PANEL_PORT}

# Backups
BACKUP_DIR=/var/lib/nexuspanel/backups
BACKUP_INTERVAL_HOURS=24

# Node agent image (built by installer if node/Dockerfile exists)
NODE_AGENT_IMAGE=nexuspanel/node:latest
EOF
  chmod 600 "$env_file"

  # Stash creds so we can print them at the end.
  ADMIN_USERNAME="$admin_user"
  ADMIN_PASSWORD="$admin_pass"
  export ADMIN_USERNAME ADMIN_PASSWORD
}

fetch_repo() {
  if [ -d "${APP_DIR}/.git" ]; then
    log "Updating ${APP_NAME} source..."
    git -C "${APP_DIR}" fetch --depth 1 origin "${REPO_BRANCH}" >/dev/null 2>&1
    git -C "${APP_DIR}" reset --hard "origin/${REPO_BRANCH}" >/dev/null 2>&1
  else
    log "Fetching ${APP_NAME} source into ${APP_DIR}..."
    mkdir -p "$(dirname "${APP_DIR}")"
    git clone --depth 1 -b "${REPO_BRANCH}" "${REPO_URL}" "${APP_DIR}" >/dev/null 2>&1 \
      || die "Failed to clone ${REPO_URL}. Set REPO_URL to a reachable repository."
  fi
}

install_cli() {
  log "Installing 'nexuspanel' command..."
  if [ -f "${APP_DIR}/scripts/nexuspanel.sh" ]; then
    cp "${APP_DIR}/scripts/nexuspanel.sh" "${BIN_PATH}"
  elif [ -f "$0" ] && [ "$0" != "${BIN_PATH}" ]; then
    cp "$0" "${BIN_PATH}"
  else
    curl -fsSL "${SCRIPT_URL}" -o "${BIN_PATH}" 2>/dev/null || true
  fi
  chmod +x "${BIN_PATH}" 2>/dev/null || true
}

build_node_image() {
  if [ ! -f "${APP_DIR}/node/Dockerfile" ]; then
    warn "node/Dockerfile not found; skip node-agent image build."
    return
  fi
  log "Building nexuspanel/node agent image (SSH provisioning)..."
  if docker build -t nexuspanel/node:latest "${APP_DIR}/node"; then
    ok "Node image: nexuspanel/node:latest"
  else
    warn "Node image build failed. Build manually: docker build -t nexuspanel/node:latest ${APP_DIR}/node"
  fi
}

wait_for_panel() {
  local url="http://127.0.0.1:${PANEL_PORT}/api/setup/status"
  log "Waiting for panel API (migrations may take 1–3 minutes on first install)..."
  for i in $(seq 1 90); do
    if panel_is_listening; then
      ok "Panel API is up."
      return 0
    fi
    if [ $((i % 15)) -eq 0 ]; then
      log "Still starting... (${i}/90)"
    fi
    sleep 2
  done
  warn "Panel API did not respond in time. Check: nexuspanel logs"
}

# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
cmd_install() {
  need_root
  echo "${BOLD}Installing NexusPanel...${NC}"
  prepare_low_memory
  install_deps
  fetch_repo
  seed_data_dir
  write_env
  configure_firewall
  install_cli
  log "Building and starting panel (first run may take a few minutes)..."
  compose up -d --build
  if [ "${SKIP_NODE_BUILD:-0}" = "1" ]; then
    warn "SKIP_NODE_BUILD=1 — node image skipped (build later: docker build -t nexuspanel/node:latest ${APP_DIR}/node)"
  else
    build_node_image
  fi
  wait_for_panel
  ok "NexusPanel is up."
  print_access
}

print_access() {
  load_env_creds
  local ip ver panel_state node_state
  ip="$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$ip" ] || ip="YOUR_SERVER_IP"
  ver="unknown"
  if [ -d "${APP_DIR}/.git" ]; then
    ver="$(git -C "${APP_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  fi
  if panel_is_listening; then
    panel_state="${GREEN}listening on :${PANEL_PORT}${NC}"
  elif compose ps --status running 2>/dev/null | grep -q nexuspanel; then
    panel_state="${YELLOW}container up but API down${NC} (run: nexuspanel logs)"
  else
    panel_state="${RED}not running${NC} (run: nexuspanel up)"
  fi
  if docker image inspect nexuspanel/node:latest >/dev/null 2>&1; then
    node_state="${GREEN}built${NC}"
  else
    node_state="${YELLOW}missing${NC} (run: docker build -t nexuspanel/node:latest ${APP_DIR}/node)"
  fi
  echo
  echo "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
  echo "${BOLD}${GREEN}║              NexusPanel — install complete           ║${NC}"
  echo "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
  echo
  echo "  ${BOLD}Panel${NC}      Multi-tenant VPN panel (Xray) + white-label + node provisioning"
  echo "  ${BOLD}Version${NC}    git ${ver}  |  API port ${PANEL_PORT}"
  echo "  ${BOLD}Status${NC}     panel: ${panel_state}   |   node image: ${node_state}"
  echo "  ${BOLD}Data${NC}       ${DATA_DIR}"
  echo
  echo "  ${BOLD}Dashboard${NC}  http://${ip}:${PANEL_PORT}/dashboard/"
  echo "  ${BOLD}System${NC}     http://${ip}:${PANEL_PORT}/dashboard/#/system"
  echo "  ${BOLD}API docs${NC}   http://${ip}:${PANEL_PORT}/docs"
  if [ -n "${ADMIN_USERNAME:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    echo
    echo "  ${BOLD}Admin login${NC}"
    echo "    Username : ${BOLD}${ADMIN_USERNAME}${NC}"
    echo "    Password : ${BOLD}${ADMIN_PASSWORD}${NC}"
    echo "  ${YELLOW}↳ Save now. Also in: ${APP_DIR}/.env (SUDO_USERNAME / SUDO_PASSWORD)${NC}"
  else
    echo
    echo "  ${YELLOW}Admin credentials: see ${APP_DIR}/.env (SUDO_USERNAME / SUDO_PASSWORD)${NC}"
  fi
  echo
  echo "  ${BOLD}Commands${NC}   nexuspanel check | info | status | logs | update | backup"
  echo "  ${YELLOW}First login → Setup wizard (tenants, branding, provisioning, tunnels).${NC}"
  echo
}

cmd_info() {
  need_root
  [ -d "${APP_DIR}" ] || die "NexusPanel not installed in ${APP_DIR}"
  print_access
}

cmd_doctor() {
  need_root
  [ -d "${APP_DIR}" ] || die "NexusPanel not installed in ${APP_DIR}"
  load_env_creds
  local url="http://127.0.0.1:${PANEL_PORT}"
  echo "${BOLD}NexusPanel diagnostics${NC}"
  echo
  compose ps 2>/dev/null || true
  echo
  if [ -f "${APP_DIR}/app/dashboard-next/out/dashboard/index.html" ]; then
    ok "Host: dashboard-next build present"
  else
    err "Host: missing ${APP_DIR}/app/dashboard-next/out/dashboard/index.html — run: cd ${APP_DIR} && ./build_dashboard.sh"
  fi
  if compose exec -T "${APP_NAME}" test -f /code/app/dashboard-next/out/dashboard/index.html 2>/dev/null; then
    ok "Container: dashboard-next build present"
  else
    err "Container: dashboard-next build missing — rebuild: docker compose up -d --build"
  fi
  local code api_code
  code="$(curl -sf -o /dev/null -w '%{http_code}' "${url}/dashboard/" 2>/dev/null || echo '000')"
  api_code="$(curl -sf -o /dev/null -w '%{http_code}' "${url}/api/setup/status" 2>/dev/null || echo '000')"
  if [ "$code" = "200" ]; then ok "Local ${url}/dashboard/ → HTTP $code"; else
    err "Local ${url}/dashboard/ → HTTP $code (expected 200). Check: nexuspanel logs"
  fi
  if [ "$api_code" = "200" ]; then ok "Local ${url}/api/setup/status → HTTP $api_code"; else
    warn "API ${url}/api/setup/status → HTTP $api_code"
  fi
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    if ufw status | grep -q "${PANEL_PORT}/tcp.*ALLOW"; then
      ok "UFW: port ${PANEL_PORT} allowed"
    else
      warn "UFW is active but port ${PANEL_PORT} may be blocked. Run: ufw allow ${PANEL_PORT}/tcp"
    fi
  fi
  local ip; ip="$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
  echo
  echo "  Open in browser: ${BOLD}http://${ip}:${PANEL_PORT}/dashboard/${NC} (use http, not https)"
  echo "  If local tests pass but browser fails → open port ${PANEL_PORT} in your VPS/cloud firewall."
  echo
}

cmd_update()  {
  need_root
  fetch_repo
  seed_data_dir
  load_env_creds
  configure_firewall
  install_cli
  compose up -d --build
  wait_for_panel
  ok "Updated."
  print_access
}
cmd_up()      { need_root; compose up -d; ok "Started."; }
cmd_down()    { need_root; compose down; ok "Stopped."; }
cmd_restart() { need_root; compose restart; ok "Restarted."; }
cmd_status()  { compose ps; }
cmd_logs()    { compose logs -f --tail=200; }
cmd_cli()     { need_root; compose exec -T ${APP_NAME} nexuspanel-cli "$@"; }

cmd_backup() {
  need_root
  local ts out; ts="$(date -u +%Y%m%d-%H%M%S)"; out="${DATA_DIR}/backups/backup-${ts}.tar.gz"
  log "Creating backup..."
  # Archive the data dir (db, xray config) plus the .env, excluding old backups.
  tar -czf "${out}" \
    -C "${DATA_DIR}" --exclude='./backups' . \
    -C "${APP_DIR}" .env 2>/dev/null || tar -czf "${out}" -C "${DATA_DIR}" --exclude='./backups' .
  ok "Backup written to ${out}"
}

cmd_restore() {
  need_root
  local file="${1:-}"; [ -n "$file" ] && [ -f "$file" ] || die "Usage: nexuspanel restore <backup.tar.gz>"
  warn "Restoring will overwrite current data."
  compose down || true
  tar -xzf "$file" -C "${DATA_DIR}"
  compose up -d
  ok "Restored from ${file}"
}

cmd_uninstall() {
  need_root
  read -r -p "${YELLOW}Remove NexusPanel and ALL data? [y/N]: ${NC}" ans
  case "${ans:-N}" in
    y|Y)
      compose down -v 2>/dev/null || true
      rm -rf "${APP_DIR}" "${BIN_PATH}"
      warn "Kept ${DATA_DIR} (your data). Remove it manually if you really want to."
      ok "Uninstalled."
      ;;
    *) log "Aborted." ;;
  esac
}

usage() {
  cat <<EOF
${BOLD}NexusPanel manager${NC}

Usage: ${APP_NAME} <command>

  install            Install and start NexusPanel
  update             Pull latest and rebuild
  up | down | restart
  status             Show container status
  info               Show panel URL, admin login, and paths
  check | doctor     Check dashboard/API locally and firewall hints
  logs               Tail logs
  backup             Create a backup archive
  restore <file>     Restore from a backup archive
  cli <args...>      Run nexuspanel-cli inside the container
  uninstall          Remove the app (keeps data dir)
EOF
}

main() {
  local cmd="${1:-install}"; shift || true
  case "$cmd" in
    install)   cmd_install "$@";;
    update)    cmd_update "$@";;
    up)        cmd_up "$@";;
    down)      cmd_down "$@";;
    restart)   cmd_restart "$@";;
    status)    cmd_status "$@";;
    info)      cmd_info "$@";;
    check|doctor) cmd_doctor "$@";;
    logs)      cmd_logs "$@";;
    backup)    cmd_backup "$@";;
    restore)   cmd_restore "$@";;
    cli)       cmd_cli "$@";;
    uninstall) cmd_uninstall "$@";;
    -h|--help|help) usage;;
    *) usage; exit 1;;
  esac
}

main "$@"
