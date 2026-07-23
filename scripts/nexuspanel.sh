#!/usr/bin/env bash
#
# NexusPanel installer & manager (branded host console).
#
# One-line install (run as root):
#   bash <(curl -fsSL https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/master/scripts/nexuspanel.sh) install
#
# Interactive shell installer (Nexus-branded menus in this terminal).
# Browser wizard: WEB_WIZARD=1 install
# Plain CLI:       SKIP_WIZARD=1 install
#
# After install, manage with:
#   nexus                 interactive host console
#   nexuspanel <command>  install | update | up | down | restart | status | logs
#                         backup | restore <file> | cli ... | uninstall | https
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
# Optional: set DOMAIN (and EMAIL) to get a domain TLS cert; otherwise an
# IP-address certificate is issued automatically. Set SKIP_HTTPS=1 to opt out.
DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"
SKIP_HTTPS="${SKIP_HTTPS:-0}"
SCRIPT_URL="${SCRIPT_URL:-https://raw.githubusercontent.com/KhaJehAmiri/nexuspanel/${REPO_BRANCH}/scripts/nexuspanel.sh}"
BIN_PATH="/usr/local/bin/${APP_NAME}"

# Brand palette (matches dashboard --nx-accent + host `nexus` console)
if [ -t 1 ]; then
  RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'
  BOLD=$'\e[1m'; NC=$'\e[0m'; WHITE=$'\e[37m'
  BRAND=$'\e[38;5;80m'; BRAND_DIM=$'\e[38;5;73m'
  MUTED=$'\e[38;5;245m'; OKC=$'\e[38;5;78m'; BADC=$'\e[38;5;203m'
else
  RED=""; GREEN=""; YELLOW=""; BLUE=""; BOLD=""; NC=""; WHITE=""
  BRAND=""; BRAND_DIM=""; MUTED=""; OKC=""; BADC=""
fi

log()  { echo "${BRAND}[*]${NC} $*"; }
ok()   { echo "${OKC}[✓]${NC} $*"; }
warn() { echo "${YELLOW}[!]${NC} $*"; }
err()  { echo "${BADC}[x]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

# ── Clean summary box primitives ──────────────────────────────────────────
# A single, aligned box for the post-install summary so operators can see the
# panel URL and credentials at a glance instead of hunting through log lines.
BOX_INNER=68  # visible columns between the left/right borders

_rep() { # $1=count $2=char  -> repeats char count times (no external deps)
  local n="$1" ch="$2" out=''
  while [ "$n" -gt 0 ]; do out="${out}${ch}"; n=$((n - 1)); done
  printf '%s' "$out"
}

# Visible column width of a string, independent of the shell's locale. Under a
# C/POSIX locale ${#str} counts *bytes*, so multibyte glyphs (◆ — ·) would
# throw the box borders out of alignment. We drop UTF-8 continuation bytes
# (0x80–0xBF) so the remaining byte count equals the number of code points,
# which for the box glyphs equals their display width.
_vwidth() {
  ( LC_ALL=C; local s="${1//[$'\x80'-$'\xBF']/}"; printf '%s' "${#s}" )
}

box_top() { printf '%b╭%s╮%b\n' "$BRAND" "$(_rep "$BOX_INNER" '─')" "$NC"; }
box_bot() { printf '%b╰%s╯%b\n' "$BRAND" "$(_rep "$BOX_INNER" '─')" "$NC"; }
box_sep() { printf '%b├%s┤%b\n' "$BRAND" "$(_rep "$BOX_INNER" '─')" "$NC"; }

box_head() { # $1 = title text (bold, brand-tinted)
  local text="$1" pad
  pad=$(( BOX_INNER - $(_vwidth "$text") - 2 ))
  [ "$pad" -lt 0 ] && pad=0
  printf '%b│%b %b%s%b%*s %b│%b\n' \
    "$BRAND" "$NC" "${BOLD}${BRAND}" "$text" "$NC" "$pad" '' "$BRAND" "$NC"
}

box_kv() { # $1=label $2=value [$3=value color]
  local label="$1" value="$2" vcolor="${3:-${BOLD}${WHITE}}" pad
  pad=$(( BOX_INNER - $(_vwidth "$(printf ' %-12s%s' "$label" "$value")") - 1 ))
  [ "$pad" -lt 0 ] && pad=0
  printf '%b│%b %b%-12s%b%b%s%b%*s %b│%b\n' \
    "$BRAND" "$NC" "$MUTED" "$label" "$NC" "$vcolor" "$value" "$NC" "$pad" '' "$BRAND" "$NC"
}

box_note() { # $1=text [$2=color]  full-width single-column line
  local text="$1" color="${2:-$MUTED}" pad
  pad=$(( BOX_INNER - $(_vwidth "$text") - 2 ))
  [ "$pad" -lt 0 ] && pad=0
  printf '%b│%b %b%s%b%*s %b│%b\n' \
    "$BRAND" "$NC" "$color" "$text" "$NC" "$pad" '' "$BRAND" "$NC"
}

need_root() {
  [ "$(id -u)" -eq 0 ] || die "Please run as root (sudo)."
}

rand() { head -c "${1:-32}" /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c "${1:-32}"; }

gen_dashboard_path() {
  echo "/$(rand 16)/"
}

INSTALLER_PORT="${INSTALLER_PORT:-8765}"
SKIP_WIZARD="${SKIP_WIZARD:-0}"
WEB_WIZARD="${WEB_WIZARD:-0}"
INSTALL_CONFIG_FILE="${DATA_DIR}/.install-config.json"
INSTALL_PROGRESS_FILE="${DATA_DIR}/.install-progress.json"
WIZARD_PID=""

write_progress() {
  local step="${1:-working}"
  local pct="${2:-0}"
  local msg="${3:-}"
  local done="${4:-false}"
  local extra="${5:-}"
  mkdir -p "${DATA_DIR}"
  if [ -n "$extra" ]; then
    python3 - "$step" "$pct" "$msg" "$done" "$extra" <<'PY'
import json, sys
step, pct, msg, done, extra = sys.argv[1:6]
payload = {"step": step, "pct": int(pct), "msg": msg, "done": done.lower() == "true"}
try:
    payload.update(json.loads(extra))
except Exception:
    pass
print(json.dumps(payload, ensure_ascii=False))
PY
  else
    python3 - "$step" "$pct" "$msg" "$done" <<'PY'
import json, sys
step, pct, msg, done = sys.argv[1:5]
print(json.dumps({"step": step, "pct": int(pct), "msg": msg, "done": done.lower() == "true"}, ensure_ascii=False))
PY
  fi > "${INSTALL_PROGRESS_FILE}"
  print_install_progress "$pct" "$msg" "$done"
}

print_install_progress() {
  local pct="${1:-0}" msg="${2:-}" done="${3:-false}"
  local bar_w=28 filled empty bar="" i
  pct="${pct//[^0-9]/}"
  [ -n "$pct" ] || pct=0
  filled=$(( pct * bar_w / 100 ))
  empty=$(( bar_w - filled ))
  for ((i = 0; i < filled; i++)); do bar+="█"; done
  for ((i = 0; i < empty; i++)); do bar+="░"; done
  if [ "$done" = "true" ]; then
    echo -e "  ${OKC}◆${NC} ${BRAND}[${pct}%]${NC} ${bar}  ${msg}"
  else
    printf "  ${BRAND}◆${NC} ${BRAND}[%3s%%]${NC} ${bar}  %s\r" "$pct" "$msg"
  fi
}

print_install_phase_banner() {
  echo
  printf "%b" "$BRAND"
  cat <<'EOF'
      ╭──╮
   ◆──┤ NX ├──◆
      ╰──╯
EOF
  printf "%b" "$NC"
  echo "  ${BOLD}${BRAND}NEXUS${NC} ${BOLD}PANEL${NC}  ${MUTED}installing…${NC}"
  echo "  ${MUTED}──────────────────────────────────────────────${NC}"
  echo
}

load_install_config() {
  [ -f "${INSTALL_CONFIG_FILE}" ] || return 0
  eval "$(python3 - "${INSTALL_CONFIG_FILE}" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
def emit(k, v):
    if v is None: return
    s = str(v).replace("'", "'\\''")
    print(f"{k}='{s}'")
if cfg.get("domain"): emit("DOMAIN", cfg["domain"])
if cfg.get("email"): emit("EMAIL", cfg["email"])
emit("SKIP_HTTPS", "1" if cfg.get("skip_https") else "0")
emit("PANEL_DEFAULT_LANG", cfg.get("panel_default_lang") or "en")
emit("PANEL_TITLE", cfg.get("panel_title") or "NexusPanel")
emit("PRIMARY_COLOR", cfg.get("primary_color") or "#2ee0c4")
emit("SUPPORT_URL", cfg.get("support_url") or "")
if cfg.get("panel_port"): emit("PANEL_PORT", cfg["panel_port"])
emit("SKIP_NODE_BUILD", "1" if cfg.get("skip_node_build", True) else "0")
emit("CONFIGURE_FIREWALL", "1" if cfg.get("configure_firewall", True) else "0")
if cfg.get("dashboard_path"): emit("DASHBOARD_PATH", cfg["dashboard_path"])
if cfg.get("admin_username"): emit("ADMIN_USERNAME", cfg["admin_username"])
if cfg.get("admin_password"): emit("ADMIN_PASSWORD", cfg["admin_password"])
emit("AUTO_CREDENTIALS", "1" if cfg.get("auto_credentials", True) else "0")
PY
)"
  export DOMAIN EMAIL SKIP_HTTPS PANEL_DEFAULT_LANG PANEL_TITLE PRIMARY_COLOR SUPPORT_URL
  export PANEL_PORT SKIP_NODE_BUILD CONFIGURE_FIREWALL DASHBOARD_PATH
  export ADMIN_USERNAME ADMIN_PASSWORD AUTO_CREDENTIALS
}

print_wizard_banner() {
  local ip="$1"
  echo
  printf "%b" "$BRAND"
  cat <<'EOF'
      ╭──╮
   ◆──┤ NX ├──◆
      ╰──╯
EOF
  printf "%b" "$NC"
  echo "  ${BOLD}${BRAND}NEXUS${NC} ${BOLD}PANEL${NC}  ${MUTED}web installer${NC}"
  echo "  ${MUTED}──────────────────────────────────────────────${NC}"
  echo "  ${BRAND}●${NC} Open in browser:"
  echo "       ${BOLD}http://${ip}:${INSTALLER_PORT}/${NC}"
  echo "       ${MUTED}http://127.0.0.1:${INSTALLER_PORT}/${NC}  (SSH port-forward)"
  echo
  echo "  ${MUTED}فارسی:${NC} مرورگر → آدرس بالا → زبان، SSL، ادمین → Install"
  echo "  ${MUTED}EN:${NC}    Open the URL → language, HTTPS, admin → Install"
  echo
  echo "  ${YELLOW}Keep this terminal open until install finishes (Ctrl+C to cancel).${NC}"
  echo
}

wizard_is_ready() {
  curl -fsS --max-time 2 "http://127.0.0.1:${INSTALLER_PORT}/" >/dev/null 2>&1
}

start_shell_installer() {
  local wiz="${APP_DIR}/scripts/installer/shell_wizard.sh"
  if [ ! -f "$wiz" ]; then
    warn "Shell installer missing — falling back."
    return 1
  fi
  mkdir -p "${DATA_DIR}"
  rm -f "${INSTALL_CONFIG_FILE}"
  write_progress "waiting" 0 "Waiting for installer configuration…" false
  log "Starting NexusPanel installer wizard…"
  chmod +x "$wiz"
  if bash "$wiz" --config "${INSTALL_CONFIG_FILE}"; then
    ok "Install configuration received."
    load_install_config
    write_progress "deps" 8 "Configuration saved — preparing install…" false
    return 0
  fi
  if [ ! -f "${INSTALL_CONFIG_FILE}" ]; then
    die "Install cancelled."
  fi
  return 1
}

start_tui_installer() {
  local tui_py="${APP_DIR}/scripts/installer/tui_wizard.py"
  if [ ! -f "$tui_py" ]; then
    return 1
  fi
  mkdir -p "${DATA_DIR}"
  rm -f "${INSTALL_CONFIG_FILE}"
  write_progress "waiting" 0 "Waiting for installer configuration…" false
  log "Starting NexusPanel terminal installer…"
  if python3 "$tui_py" --config "${INSTALL_CONFIG_FILE}"; then
    ok "Install configuration received."
    load_install_config
    write_progress "deps" 8 "Configuration saved — preparing install…" false
    return 0
  fi
  local rc=$?
  if [ "$rc" -eq 1 ]; then
    die "Install cancelled."
  fi
  return 1
}

run_install_wizard() {
  if [ "${SKIP_WIZARD}" = "1" ]; then
    prompt_install_config
    return 1
  fi
  if [ "${WEB_WIZARD}" = "1" ]; then
    start_install_wizard
    return $?
  fi
  if start_shell_installer; then
    return 0
  fi
  warn "Shell wizard unavailable — trying curses TUI, web, or CLI."
  if start_tui_installer; then
    return 0
  fi
  if start_install_wizard; then
    return 0
  fi
  prompt_install_config
  return 1
}

start_install_wizard() {
  local wizard_py="${APP_DIR}/scripts/installer/wizard_server.py"
  if [ ! -f "$wizard_py" ]; then
    warn "Web installer UI missing in ${APP_DIR}/scripts/installer/"
    if [ -t 0 ]; then
      prompt_install_config
      return 1
    fi
    die "Web installer files not found after git clone. Run: nexuspanel update && nexuspanel install"
  fi
  if [ "${SKIP_WIZARD}" = "1" ]; then
    prompt_install_config
    return 1
  fi
  mkdir -p "${DATA_DIR}"
  rm -f "${INSTALL_CONFIG_FILE}"
  write_progress "waiting" 0 "Waiting for installer configuration…" false
  log "Starting NexusPanel web installer on port ${INSTALLER_PORT}…"
  python3 "$wizard_py" \
    --port "${INSTALLER_PORT}" \
    --config "${INSTALL_CONFIG_FILE}" \
    --progress "${INSTALL_PROGRESS_FILE}" &
  WIZARD_PID=$!
  local ip tries=0
  while ! wizard_is_ready; do
    sleep 1
    tries=$((tries + 1))
    if ! kill -0 "${WIZARD_PID}" 2>/dev/null; then
      if [ -t 0 ]; then
        warn "Installer UI stopped unexpectedly — falling back to CLI prompts."
        prompt_install_config
        return 1
      fi
      die "Web installer failed to start on port ${INSTALLER_PORT}. Check: python3, firewall, port in use."
    fi
    if [ "$tries" -ge 30 ]; then
      die "Web installer did not respond on port ${INSTALLER_PORT} after 30s."
    fi
  done
  ip="$(curl -fsSL --max-time 6 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$ip" ] || ip="YOUR_SERVER_IP"
  if command -v ufw >/dev/null 2>&1; then
    ufw allow "${INSTALLER_PORT}/tcp" comment 'NexusPanel installer (temporary)' >/dev/null 2>&1 || true
  fi
  print_wizard_banner "$ip"
  local waited=0 last_reminder=0
  while [ ! -f "${INSTALL_CONFIG_FILE}" ]; do
    sleep 1
    waited=$((waited + 1))
    if ! kill -0 "${WIZARD_PID}" 2>/dev/null; then
      if [ -t 0 ]; then
        warn "Installer UI stopped unexpectedly — falling back to CLI prompts."
        prompt_install_config
        return 1
      fi
      die "Web installer stopped. Open http://${ip}:${INSTALLER_PORT}/ in your browser and re-run install."
    fi
    if [ $((waited - last_reminder)) -ge 30 ]; then
      last_reminder=$waited
      echo "  ${YELLOW}Still waiting — open:${NC} ${BOLD}http://${ip}:${INSTALLER_PORT}/${NC}"
    fi
    if [ "$waited" -ge 3600 ]; then
      die "Timed out waiting for installer configuration (1 hour). Open http://${ip}:${INSTALLER_PORT}/"
    fi
  done
  ok "Install configuration received."
  load_install_config
  write_progress "deps" 8 "Configuration saved — preparing install…" false
  return 0
}

stop_install_wizard() {
  if [ -n "${WIZARD_PID}" ] && kill -0 "${WIZARD_PID}" 2>/dev/null; then
    kill "${WIZARD_PID}" 2>/dev/null || true
    wait "${WIZARD_PID}" 2>/dev/null || true
  fi
  if command -v ufw >/dev/null 2>&1; then
    ufw delete allow "${INSTALLER_PORT}/tcp" >/dev/null 2>&1 || true
  fi
}

prompt_install_config() {
  if [ ! -t 0 ]; then
    warn "Non-interactive shell — using defaults (DOMAIN empty, auto HTTPS on IP)."
    warn "For full options use the web wizard: bash <(curl -fsSL ${SCRIPT_URL}) install"
    return 0
  fi
  if [ -z "${DOMAIN:-}" ]; then
    echo
    read -r -p "Domain for HTTPS (leave empty = certificate on public IP): " DOMAIN || true
    DOMAIN="${DOMAIN// /}"
  fi
  if [ -n "${DOMAIN:-}" ] && [ -z "${EMAIL:-}" ]; then
    read -r -p "Email for Let's Encrypt (optional): " EMAIL || true
    EMAIL="${EMAIL// /}"
  fi
}

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
  if [ "${SKIP_NODE_BUILD:-}" = "" ]; then
    SKIP_NODE_BUILD=1
    log "Skipping node-agent build during install (build later: docker build -t nexuspanel/node:latest ${APP_DIR}/node)"
  fi
}

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.postgres.yml}"

ensure_docker_gid() {
  local env_file="${APP_DIR}/.env"
  [ -f "$env_file" ] || return 0
  local gid
  gid="$(getent group docker 2>/dev/null | cut -d: -f3)"
  [ -n "$gid" ] || gid="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo 988)"
  if grep -q '^DOCKER_GID=' "$env_file" 2>/dev/null; then
    sed -i "s/^DOCKER_GID=.*/DOCKER_GID=${gid}/" "$env_file"
  else
    printf '\n# Docker socket GID (in-dashboard updates)\nDOCKER_GID=%s\n' "$gid" >> "$env_file"
  fi
}

# Panel container runs as uid 1000; bind-mount makes host files visible at /code.
ensure_code_permissions() {
  [ -d "${APP_DIR}" ] || return 0
  local env_file="${APP_DIR}/.env"
  if [ -f "$env_file" ]; then
    chown 1000:1000 "$env_file" 2>/dev/null || true
    chmod 600 "$env_file"
  fi
}

git_app() {
  git -c "safe.directory=${APP_DIR}" -C "${APP_DIR}" "$@"
}

ensure_data_permissions() {
  mkdir -p "${DATA_DIR}/backups" "${DATA_DIR}/xray-tls"
  chown 1000:1000 "${DATA_DIR}/backups" "${DATA_DIR}/xray-tls" 2>/dev/null || true
  chmod 750 "${DATA_DIR}/xray-tls" 2>/dev/null || true
  chown -R 1000:1000 "${DATA_DIR}/xray-tls" 2>/dev/null || true
  for path in "${DATA_DIR}/xray_config.json" "${DATA_DIR}/install-meta.json"; do
    if [ -f "$path" ]; then
      chown 1000:1000 "$path" 2>/dev/null || true
      chmod 664 "$path" 2>/dev/null || true
    fi
  done
}

write_install_meta() {
  local ver sha meta
  ver="$(tr -d '[:space:]' < "${APP_DIR}/VERSION" 2>/dev/null || echo "0.0.0")"
  sha="$(git -c "safe.directory=${APP_DIR}" -C "${APP_DIR}" rev-parse --short HEAD 2>/dev/null || true)"
  meta="${DATA_DIR}/install-meta.json"
  python3 - "$meta" "$ver" "$sha" <<'PY'
import json, sys, time
path, ver, sha = sys.argv[1:4]
payload = {"version": ver, "updated_at": int(time.time())}
if sha:
    payload["sha"] = sha
open(path, "w", encoding="utf-8").write(json.dumps(payload, indent=2))
PY
}

compose() {
  local -a env_args=()
  local -a file_args=(-f "${APP_DIR}/${COMPOSE_FILE}")
  [ -f "${APP_DIR}/.env" ] && env_args+=(--env-file "${APP_DIR}/.env")
  [ -f "${RUNTIME_ENV_FILE}" ] && env_args+=(--env-file "${RUNTIME_ENV_FILE}")
  # Autostart toggle (nexus 15/16) writes this; -f disables automatic merge.
  if [ -f "${APP_DIR}/docker-compose.override.yml" ]; then
    file_args+=(-f "${APP_DIR}/docker-compose.override.yml")
  fi
  if docker compose version >/dev/null 2>&1; then
    docker compose -p nexuspanel "${file_args[@]}" "${env_args[@]}" "$@"
  else
    docker-compose -p nexuspanel "${file_args[@]}" "${env_args[@]}" "$@"
  fi
}

# Docker install must not compete with a host systemd unit on :8000.
disable_conflicting_services() {
  if systemctl is-enabled nexuspanel.service >/dev/null 2>&1; then
    warn "Disabling host systemd unit (nexuspanel.service) — Docker owns the panel."
    systemctl stop nexuspanel.service >/dev/null 2>&1 || true
    systemctl disable nexuspanel.service >/dev/null 2>&1 || true
  fi
}

panel_http_code() {
  local path="${1:-/api/setup/status}"
  curl -sf -o /dev/null -w '%{http_code}' --max-time 3 -X GET "http://127.0.0.1:${PANEL_PORT}${path}" 2>/dev/null || echo "000"
}

panel_is_listening() {
  [ "$(panel_http_code /api/setup/status)" = "200" ]
}

# Default Xray inbound ports (documented alongside xray_config.default.json).
XRAY_INBOUND_PORTS="8443 2095 2096 2097 1080"

# Ensure data dir has required files (safe to run on install and update).
seed_data_dir() {
  mkdir -p "${DATA_DIR}" "${DATA_DIR}/backups"
  local target="${DATA_DIR}/xray_config.json"
  local source="${APP_DIR}/xray_config.default.json"
  [ -f "${source}" ] || return 0
  if [ ! -f "${target}" ]; then
    cp "${source}" "${target}"
    chown 1000:1000 "${target}" 2>/dev/null || true
    ok "Created ${target} from install template"
    return 0
  fi
  # Upgrade legacy single-protocol (Shadowsocks-only) default to the current
  # empty install template. Do not touch configs that are already empty or
  # intentionally have no vless/vmess (e.g. wireguard-only or zero inbounds).
  if grep -q '"shadowsocks"' "${target}" \
    && ! grep -q '"vless"' "${target}" \
    && ! grep -q '"vmess"' "${target}" \
    && ! grep -q '"trojan"' "${target}"; then
    cp "${target}" "${target}.bak.$(date +%s)"
    cp "${source}" "${target}"
    ok "Upgraded ${target} to empty multi-protocol-ready template; old config backed up."
  fi
}

# Detect the active SSH port(s) so the firewall never locks the operator out.
detect_ssh_ports() {
  local ports
  ports="$(grep -ahiE '^[[:space:]]*Port[[:space:]]+[0-9]+' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | awk '{print $2}' | sort -u)"
  [ -z "$ports" ] && ports="$(ss -tlnp 2>/dev/null | awk '/sshd/{split($4,a,":"); print a[length(a)]}' | sort -u)"
  [ -z "$ports" ] && ports="22"
  echo "$ports"
}

# Open HTTPS (443), HTTP-for-redirect/ACME (80), SSH and Xray inbound ports in
# UFW when present. The app port (PANEL_PORT) is NOT opened — it is bound to
# localhost and only reachable through the nginx TLS proxy. Never enables an
# inactive UFW (avoids SSH lockout).
configure_firewall() {
  [ "${CONFIGURE_FIREWALL:-1}" = "1" ] || { log "Skipping UFW configuration (disabled in installer)."; return 0; }
  command -v ufw >/dev/null 2>&1 || return 0
  log "Configuring firewall (UFW) for HTTPS + SSH + inbound ports..."
  local ssh_ports; ssh_ports="$(detect_ssh_ports)"
  for sp in ${ssh_ports}; do
    ufw allow "${sp}/tcp" comment 'SSH' >/dev/null 2>&1 || true
  done
  ufw allow 80/tcp  comment 'HTTP (redirect + ACME)' >/dev/null 2>&1 || true
  ufw allow 443/tcp comment 'NexusPanel HTTPS' >/dev/null 2>&1 || true
  for p in ${XRAY_INBOUND_PORTS}; do
    ufw allow "${p}" comment 'NexusPanel Xray inbound' >/dev/null 2>&1 || true
  done
  if ufw status 2>/dev/null | grep -qi "Status: active"; then
    ok "UFW: SSH (${ssh_ports}), 80/443 and inbound ports allowed; app port ${PANEL_PORT} stays private."
  else
    ok "UFW rules added (firewall not enabled — enable manually if you use UFW)."
  fi
}

# Put the panel behind nginx with a real TLS certificate (IP or domain).
setup_tls() {
  if [ "${SKIP_HTTPS}" = "1" ]; then
    warn "SKIP_HTTPS=1 — panel on http://0.0.0.0:${PANEL_PORT} (configure HTTPS yourself)."
    return 0
  fi
  local script="${APP_DIR}/scripts/setup_https.sh"
  [ -f "$script" ] || { warn "scripts/setup_https.sh missing — skipping TLS. Run it later."; return 0; }
  log "Enabling HTTPS (nginx reverse proxy + Let's Encrypt)..."
  local args=(--port "${PANEL_PORT}")
  [ -n "${DOMAIN}" ] && args+=(--domain "${DOMAIN}")
  [ -n "${EMAIL}" ]  && args+=(--email "${EMAIL}")
  if DOMAIN="${DOMAIN}" EMAIL="${EMAIL}" PANEL_PORT="${PANEL_PORT}" bash "$script" "${args[@]}"; then
    ok "HTTPS enabled."
  else
    warn "Automatic HTTPS setup did not complete. Re-run later: nexuspanel https"
    warn "(IP/domain must be reachable on port 80 for Let's Encrypt validation.)"
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
RUNTIME_ENV_FILE="${DATA_DIR}/.env"

_load_env_file() {
  local env_file="$1"
  [ -f "$env_file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -z "$line" ] && continue
    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]]; then
      local key="${BASH_REMATCH[1]}"
      local val="${BASH_REMATCH[2]}"
      val="${val#"${val%%[![:space:]]*}"}"
      val="${val%"${val##*[![:space:]]}"}"
      if [[ "$val" =~ ^\"(.*)\"$ ]] || [[ "$val" =~ ^\'(.*)\'$ ]]; then
        val="${BASH_REMATCH[1]}"
      fi
      export "${key}=${val}"
    fi
  done < "$env_file"
}

load_env_creds() {
  _load_env_file "${APP_DIR}/.env"
  _load_env_file "${RUNTIME_ENV_FILE}"
  ADMIN_USERNAME="${SUDO_USERNAME:-${ADMIN_USERNAME:-}}"
  DASHBOARD_PATH="${DASHBOARD_PATH:-/dashboard/}"
  # The runtime .env only keeps a bcrypt hash (not recoverable), but the installer
  # also drops the plaintext password into the creds file. Recover it from there so
  # a re-run / `nexuspanel info` can still show the operator their real password
  # instead of an unhelpful "set earlier" placeholder.
  if [ -z "${ADMIN_PASSWORD:-}" ] && [ -f "${DATA_DIR}/install-credentials.txt" ]; then
    local _recovered
    _recovered="$(sed -n 's/^Admin password[[:space:]]*:[[:space:]]*//p' \
      "${DATA_DIR}/install-credentials.txt" 2>/dev/null | head -n1)"
    [ -n "$_recovered" ] && ADMIN_PASSWORD="$_recovered"
  fi
  PANEL_PORT="${UVICORN_PORT:-${PANEL_PORT:-8000}}"
  export ADMIN_USERNAME ADMIN_PASSWORD PANEL_PORT DASHBOARD_PATH
}

ensure_runtime_env() {
  if [ -f "${APP_DIR}/scripts/migrate_runtime_secrets.py" ]; then
    python3 "${APP_DIR}/scripts/migrate_runtime_secrets.py" --if-needed \
      || warn "Runtime secrets migration skipped (run: python3 scripts/migrate_runtime_secrets.py)"
  fi
}

# bcrypt-hash a plaintext password using the panel's own dependency (passlib).
bcrypt_hash() { # $1 = plaintext
  python3 - "$1" <<'PY' 2>/dev/null
import sys
from passlib.hash import bcrypt
print(bcrypt.using(rounds=12).hash(sys.argv[1]))
PY
}

write_env() {
  local env_file="${APP_DIR}/.env"
  if [ -f "$env_file" ]; then
    warn ".env already exists; keeping it."
    ensure_runtime_env
    load_env_creds
    ensure_docker_gid
    ensure_code_permissions
    return
  fi

  local admin_user admin_pass hash public_ip pg_pass redis_pw dash_path cred_file
  admin_user="${ADMIN_USERNAME:-u$(rand 10)}"
  admin_pass="${ADMIN_PASSWORD:-$(rand 24)}"
  hash="$(bcrypt_hash "$admin_pass" || true)"
  public_ip="$(curl -fsSL --max-time 6 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$public_ip" ] || public_ip="127.0.0.1"
  pg_pass="$(rand 32)"
  redis_pw="$(rand 40)"
  dash_path="${DASHBOARD_PATH:-$(gen_dashboard_path)}"
  case "$dash_path" in
    */) ;;
    *) dash_path="${dash_path}/" ;;
  esac

  log "Generating configuration with random secrets..."
  mkdir -p "${DATA_DIR}"
  cat > "${RUNTIME_ENV_FILE}" <<EOF
# Runtime secrets — outside git checkout (${RUNTIME_ENV_FILE})
# Generated by nexuspanel installer on $(date -u +%FT%TZ)
SUDO_USERNAME=${admin_user}
EOF
  if [ -n "$hash" ]; then
    echo "SUDO_PASSWORD_HASH=${hash}" >> "${RUNTIME_ENV_FILE}"
  else
    warn "passlib not available — falling back to SUDO_PASSWORD (rotate to a hash later)."
    echo "SUDO_PASSWORD=${admin_pass}" >> "${RUNTIME_ENV_FILE}"
  fi
  cat >> "${RUNTIME_ENV_FILE}" <<EOF
POSTGRES_USER=nexuspanel
POSTGRES_PASSWORD=${pg_pass}
POSTGRES_DB=nexuspanel
SQLALCHEMY_DATABASE_URL=postgresql://nexuspanel:${pg_pass}@127.0.0.1:5432/nexuspanel
REDIS_PASSWORD=${redis_pw}
REDIS_URL=redis://:${redis_pw}@127.0.0.1:6379/0
NODE_BOOTSTRAP_TOKEN=$(rand 40)
NODE_CONTROL_SECRET=$(rand 40)
METRICS_TOKEN=$(rand 40)
EOF
  chmod 600 "${RUNTIME_ENV_FILE}"

  cat > "$env_file" <<EOF
# Repo configuration (no secrets — see ${RUNTIME_ENV_FILE})
# Generated by nexuspanel installer on $(date -u +%FT%TZ)

# Panel listens on all interfaces (firewall should block ${PANEL_PORT} from the public internet).
UVICORN_HOST=0.0.0.0
UVICORN_PORT=${PANEL_PORT}
ALLOWED_ORIGINS=http://${public_ip}:${PANEL_PORT}

# Secret dashboard URL path (only the admin UI — /sub/ and /portal/ stay public).
DASHBOARD_PATH=${dash_path}

XRAY_JSON=/var/lib/nexuspanel/xray_config.json
# Private paths so the non-root panel user can upgrade/downgrade Xray in-dashboard.
XRAY_EXECUTABLE_PATH=/var/lib/nexuspanel/bin/xray
XRAY_ASSETS_PATH=/var/lib/nexuspanel/share/xray

# Panel defaults (set by web installer).
PANEL_DEFAULT_LANG=${PANEL_DEFAULT_LANG:-en}
PANEL_TITLE=${PANEL_TITLE:-NexusPanel}
PRIMARY_COLOR=${PRIMARY_COLOR:-#2ee0c4}

# Address resellers' provisioned nodes use to reach this panel.
# Upgraded to https://<domain-or-ip> automatically by scripts/setup_https.sh.
PANEL_PUBLIC_ADDRESS=http://${public_ip}:${PANEL_PORT}

# Backups
BACKUP_DIR=/var/lib/nexuspanel/backups
BACKUP_INTERVAL_HOURS=24

# Node agent image (built by installer if node/Dockerfile exists)
NODE_AGENT_IMAGE=nexuspanel/node:latest
EOF
  [ -n "${SUPPORT_URL:-}" ] && echo "SUB_SUPPORT_URL=${SUPPORT_URL}" >> "$env_file"
  ensure_docker_gid
  ensure_code_permissions

  # Stash creds so we can print them at the end (password not stored in plaintext).
  ADMIN_USERNAME="$admin_user"
  ADMIN_PASSWORD="$admin_pass"
  DASHBOARD_PATH="$dash_path"
  export ADMIN_USERNAME ADMIN_PASSWORD DASHBOARD_PATH

  cred_file="${DATA_DIR}/install-credentials.txt"
  mkdir -p "${DATA_DIR}"
  cat > "$cred_file" <<CREDS
# NexusPanel install credentials — $(date -u +%FT%TZ)
# Keep this file private (chmod 600).

Admin username : ${admin_user}
Admin password : ${admin_pass}
Dashboard path : ${dash_path}
Panel port     : ${PANEL_PORT}
Database       : PostgreSQL nexuspanel@127.0.0.1:5432/nexuspanel
CREDS
  chmod 600 "$cred_file"
  ok "Credentials saved to ${cred_file}"
}

fetch_repo() {
  if [ -d "${APP_DIR}/.git" ]; then
    log "Updating ${APP_NAME} source..."
    git_app fetch --depth 1 origin "${REPO_BRANCH}" >/dev/null 2>&1
    git_app reset --hard "origin/${REPO_BRANCH}" >/dev/null 2>&1
  else
    log "Fetching ${APP_NAME} source into ${APP_DIR}..."
    mkdir -p "$(dirname "${APP_DIR}")"
    git clone --depth 1 -b "${REPO_BRANCH}" "${REPO_URL}" "${APP_DIR}" >/dev/null 2>&1 \
      || die "Failed to clone ${REPO_URL}. Set REPO_URL to a reachable repository."
  fi
}

install_cli() {
  log "Installing host commands (nexuspanel + nexus)…"
  if [ -f "${APP_DIR}/scripts/nexuspanel.sh" ]; then
    cp "${APP_DIR}/scripts/nexuspanel.sh" "${BIN_PATH}"
  elif [ -f "$0" ] && [ "$0" != "${BIN_PATH}" ]; then
    cp "$0" "${BIN_PATH}"
  else
    curl -fsSL "${SCRIPT_URL}" -o "${BIN_PATH}" 2>/dev/null || true
  fi
  chmod +x "${BIN_PATH}" 2>/dev/null || true

  # Interactive branded management console (`nexus`), like x-ui but Nexus-native.
  if [ -f "${APP_DIR}/scripts/install-nexus.sh" ]; then
    bash "${APP_DIR}/scripts/install-nexus.sh" >/dev/null 2>&1 || true
  elif [ -f "${APP_DIR}/scripts/nexus.sh" ]; then
    cat > /usr/local/bin/nexus <<EOF
#!/usr/bin/env bash
export NEXUS_APP_DIR="${APP_DIR}"
exec bash "${APP_DIR}/scripts/nexus.sh" "\$@"
EOF
    chmod +x /usr/local/bin/nexus
  fi
  ok "Commands ready: nexuspanel · nexus"
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
  log "Waiting for panel API (migrations may take 1–3 minutes on first install)..."
  for i in $(seq 1 150); do
    if panel_is_listening; then
      ok "Panel API is up."
      return 0
    fi
    if [ $((i % 15)) -eq 0 ]; then
      log "Still starting... (${i}/150)"
      compose logs --tail=8 nexuspanel 2>/dev/null | tail -5 || true
    fi
    sleep 2
  done
  warn "Panel API did not respond in time. Check: nexuspanel logs"
  compose logs --tail=40 nexuspanel 2>/dev/null || true
}

apply_install_branding() {
  [ -n "${PANEL_TITLE:-}" ] || return 0
  log "Applying panel branding from installer…"
  PANEL_TITLE="${PANEL_TITLE}" PRIMARY_COLOR="${PRIMARY_COLOR:-#2ee0c4}" SUPPORT_URL="${SUPPORT_URL:-}" \
    compose exec -T -e PANEL_TITLE -e PRIMARY_COLOR -e SUPPORT_URL nexuspanel python3 <<'PY' 2>/dev/null || true
import os
from app.db import GetDB
from app.tenant import set_branding
title = os.environ.get("PANEL_TITLE", "NexusPanel")
color = os.environ.get("PRIMARY_COLOR") or "#2ee0c4"
support = (os.environ.get("SUPPORT_URL") or "").strip()
fields = {"panel_title": title, "primary_color": color}
if support:
    fields["support_url"] = support
with GetDB() as db:
    set_branding(db, None, allow_global=True, **fields)
PY
}

# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
cmd_install() {
  need_root
  printf "%b" "$BRAND"
  cat <<'EOF'
      ╭──╮
   ◆──┤ NX ├──◆
      ╰──╯
EOF
  printf "%b" "$NC"
  echo "  ${BOLD}${BRAND}NEXUS${NC} ${BOLD}PANEL${NC}  ${MUTED}setup${NC}"
  echo "  ${MUTED}──────────────────────────────────────────────${NC}"
  echo
  prepare_low_memory
  install_deps
  fetch_repo
  local wizard_active=0
  if run_install_wizard; then
    wizard_active=1
  fi
  print_install_phase_banner
  write_progress "seed" 12 "Preparing data directory…" false
  seed_data_dir
  write_progress "env" 18 "Generating secrets and .env…" false
  write_env
  ensure_docker_gid
  ensure_code_permissions
  ensure_data_permissions
  write_progress "services" 25 "Stopping conflicting services…" false
  disable_conflicting_services
  write_progress "firewall" 30 "Configuring firewall…" false
  configure_firewall
  install_cli
  write_progress "docker" 40 "Building and starting Docker stack (may take a few minutes)…" false
  log "Building and starting panel (first run may take a few minutes)..."
  compose up -d --build
  if [ "${SKIP_NODE_BUILD:-0}" = "1" ]; then
    warn "SKIP_NODE_BUILD=1 — node image skipped (build later: docker build -t nexuspanel/node:latest ${APP_DIR}/node)"
  else
    write_progress "node" 70 "Building node-agent image…" false
    build_node_image
  fi
  write_progress "wait" 80 "Waiting for panel API…" false
  wait_for_panel
  write_progress "tls" 90 "Setting up HTTPS…" false
  setup_tls
  write_progress "branding" 95 "Applying branding…" false
  apply_install_branding
  local dash_url base_url ip
  load_env_creds
  ip="$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  base_url="$(public_base_url "$ip")"
  dash_url="$(dashboard_url "$base_url")"
  write_progress "done" 100 "Install complete" true \
    "{\"result\":{\"admin_username\":\"${ADMIN_USERNAME:-}\",\"admin_password\":\"${ADMIN_PASSWORD:-}\",\"dashboard_path\":\"${DASHBOARD_PATH:-}\",\"dashboard_url\":\"${dash_url}\"}}"
  ok "NexusPanel is up."
  print_access
  if [ -n "${WIZARD_PID}" ] && kill -0 "${WIZARD_PID}" 2>/dev/null; then
    log "Web installer will close in 30 seconds — save credentials from the browser or below."
    sleep 30
    stop_install_wizard
  fi
}

# Public base URL: prefer PANEL_PUBLIC_ADDRESS from .env, then DOMAIN, then
# https://<ip> when nginx is serving TLS, else the localhost app URL.
public_base_url() {
  local ip="$1"
  if [ -n "${PANEL_PUBLIC_ADDRESS:-}" ]; then
    case "${PANEL_PUBLIC_ADDRESS}" in http://*|https://*) echo "${PANEL_PUBLIC_ADDRESS}"; return;; esac
    echo "https://${PANEL_PUBLIC_ADDRESS}"; return
  fi
  if [ -n "${DOMAIN}" ]; then echo "https://${DOMAIN}"; return; fi
  if systemctl is-active nginx >/dev/null 2>&1; then echo "https://${ip}"; return; fi
  echo "http://${ip}:${PANEL_PORT}"
}

dashboard_url() {
  local base="$1"
  local path="${DASHBOARD_PATH:-/dashboard/}"
  case "$path" in
    */) ;;
    *) path="${path}/" ;;
  esac
  echo "${base}${path}"
}

print_access() {
  load_env_creds
  local ip ver base_url panel_txt panel_col node_txt node_col db_txt
  ip="$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$ip" ] || ip="YOUR_SERVER_IP"
  base_url="$(public_base_url "$ip")"
  local dash_url; dash_url="$(dashboard_url "$base_url")"
  ver="unknown"
  if [ -d "${APP_DIR}/.git" ]; then
    ver="$(git -C "${APP_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  fi
  if panel_is_listening; then
    panel_txt="running · listening on :${PANEL_PORT}"; panel_col="$OKC"
  elif compose ps --status running 2>/dev/null | grep -q nexuspanel; then
    panel_txt="container up, API down (run: nexuspanel logs)"; panel_col="$YELLOW"
  else
    panel_txt="not running (run: nexuspanel up)"; panel_col="$BADC"
  fi
  if docker image inspect nexuspanel/node:latest >/dev/null 2>&1; then
    node_txt="built"; node_col="$OKC"
  else
    node_txt="missing (docker build -t nexuspanel/node:latest node/)"; node_col="$YELLOW"
  fi
  db_txt="PostgreSQL · ${POSTGRES_USER:-nexuspanel}@127.0.0.1:5432/${POSTGRES_DB:-nexuspanel}"

  echo
  box_top
  box_head "◆  NEXUS PANEL — installation complete"
  box_sep
  box_head "ACCESS"
  box_kv "URL" "$dash_url" "${BOLD}${BRAND}"
  box_kv "Web Path" "${DASHBOARD_PATH}"
  box_kv "Port" "${PANEL_PORT}"
  box_kv "Subscribe" "${base_url}/sub/"
  box_kv "Portal" "${base_url}/portal/"
  case "$base_url" in
    https://*) :;;
    *) box_note "! HTTPS not enabled yet — run: nexuspanel https" "$YELLOW";;
  esac
  box_sep
  box_head "ADMIN LOGIN"
  box_kv "Username" "${ADMIN_USERNAME:-—}" "${BOLD}${WHITE}"
  if [ -n "${ADMIN_PASSWORD:-}" ]; then
    box_kv "Password" "${ADMIN_PASSWORD}" "${BOLD}${YELLOW}"
    box_note "Save it now — stored only as a bcrypt hash from here on." "$MUTED"
  else
    box_kv "Password" "not shown — recover or reset (see below)" "$YELLOW"
  fi
  if [ -f "${DATA_DIR}/install-credentials.txt" ]; then
    box_kv "Creds file" "${DATA_DIR}/install-credentials.txt" "${BOLD}${WHITE}"
    box_note "Show password: cat ${DATA_DIR}/install-credentials.txt" "$MUTED"
  else
    box_kv "Creds file" "— (file removed)" "$MUTED"
    box_note "Forgot it? Set a new one: nexus password" "$MUTED"
  fi
  box_sep
  box_head "SYSTEM"
  box_kv "Version" "git ${ver}"
  box_kv "Panel" "$panel_txt" "$panel_col"
  box_kv "Node image" "$node_txt" "$node_col"
  box_kv "Database" "$db_txt"
  box_kv "Data dir" "${DATA_DIR}" "$MUTED"
  box_sep
  box_head "MANAGE"
  box_kv "nexus" "host console (status · update · SSL · password)" "$MUTED"
  box_kv "nexuspanel" "check · info · logs · update · backup" "$MUTED"
  box_note "First login opens the in-panel setup wizard." "$MUTED"
  box_bot
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
  code="$(curl -sf -o /dev/null -w '%{http_code}' "${url}${DASHBOARD_PATH:-/dashboard/}" 2>/dev/null || echo '000')"
  api_code="$(curl -sf -o /dev/null -w '%{http_code}' "${url}/api/setup/status" 2>/dev/null || echo '000')"
  if [ "$code" = "200" ]; then ok "Local ${url}${DASHBOARD_PATH:-/dashboard/} → HTTP $code"; else
    err "Local ${url}${DASHBOARD_PATH:-/dashboard/} → HTTP $code (expected 200). Check: nexuspanel logs"
  fi
  if [ "$api_code" = "200" ]; then ok "Local ${url}/api/setup/status → HTTP $api_code"; else
    warn "API ${url}/api/setup/status → HTTP $api_code"
  fi
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    if ufw status | grep -qE "443/tcp.*ALLOW"; then
      ok "UFW: port 443 (HTTPS) allowed"
    else
      warn "UFW is active but port 443 may be blocked. Run: ufw allow 443/tcp"
    fi
  fi
  if systemctl is-active nginx >/dev/null 2>&1; then
    ok "nginx: active (TLS reverse proxy)"
  else
    warn "nginx not active — HTTPS not terminated. Run: nexuspanel https"
  fi
  local ip; ip="$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
  local base_url; base_url="$(public_base_url "$ip")"
  echo
  echo "  Open in browser: ${BOLD}$(dashboard_url "$base_url")${NC}"
  echo "  If local tests pass but browser fails → open ports 80 and 443 in your VPS/cloud firewall."
  echo
}

ensure_nginx_restarting_page() {
  # Host nginx: show waiting page instead of stock 502 while the panel restarts.
  local script="${APP_DIR}/scripts/ensure_nginx_restarting_page.sh"
  [ -f "$script" ] || return 0
  PANEL_PORT="${PANEL_PORT:-8000}" bash "$script" >/dev/null 2>&1 || true
}

cmd_https() {
  need_root
  [ -d "${APP_DIR}" ] || die "NexusPanel not installed in ${APP_DIR}"
  local script="${APP_DIR}/scripts/setup_https.sh"
  [ -f "$script" ] || die "scripts/setup_https.sh not found. Run: nexuspanel update"
  load_env_creds
  local args=(--port "${PANEL_PORT}")
  [ -n "${DOMAIN}" ] && args+=(--domain "${DOMAIN}")
  [ -n "${EMAIL}" ]  && args+=(--email "${EMAIL}")
  DOMAIN="${DOMAIN}" EMAIL="${EMAIL}" PANEL_PORT="${PANEL_PORT}" bash "$script" "${args[@]}"
  ensure_nginx_restarting_page
}

sync_agent_github_if_configured() {
  # Push cached node-agent tarball to GitHub Releases (NODE_AGENT_PACKAGE_URL).
  _load_env_file "${APP_DIR}/.env" 2>/dev/null || true
  _load_env_file "${DATA_DIR}/.env" 2>/dev/null || true
  if [ "${NODE_AGENT_GITHUB_SYNC:-1}" = "0" ] || [ "${NODE_AGENT_GITHUB_SYNC:-1}" = "false" ]; then
    return 0
  fi
  local script="${APP_DIR}/scripts/sync_agent_github.sh"
  if [ ! -f "$script" ]; then
    warn "GitHub agent package sync skipped (missing ${script})"
    return 0
  fi
  log "Syncing node agent image to GitHub Releases..."
  if NODE_AGENT_IMAGE="${NODE_AGENT_IMAGE:-nexuspanel/node:latest}" \
     NODE_AGENT_GITHUB_REPO="${NODE_AGENT_GITHUB_REPO:-}" \
     NODE_AGENT_GITHUB_TAG="${NODE_AGENT_GITHUB_TAG:-node-agent}" \
     APP_DIR="${APP_DIR}" \
     bash "$script"; then
    ok "GitHub agent package synced."
  else
    warn "GitHub agent package sync failed (nodes may fall back to Iran mirror)."
  fi
}

sync_agent_mirror_if_configured() {
  # Optional: push cached node-agent tarball to domestic (Iran) HTTP mirror.
  _load_env_file "${APP_DIR}/.env" 2>/dev/null || true
  _load_env_file "${DATA_DIR}/.env" 2>/dev/null || true
  if [ -z "${NODE_AGENT_MIRROR_SSH:-}" ] && [ -z "${NODE_AGENT_MIRROR_URL:-}" ]; then
    return 0
  fi
  if [ -z "${NODE_AGENT_MIRROR_SSH:-}" ]; then
    return 0
  fi
  local script="${APP_DIR}/scripts/sync_agent_mirror.sh"
  if [ ! -f "$script" ]; then
    warn "Agent mirror sync skipped (missing ${script})"
    return 0
  fi
  log "Syncing node agent image to Iran mirror (${NODE_AGENT_MIRROR_SSH})..."
  if NODE_AGENT_MIRROR_SSH="${NODE_AGENT_MIRROR_SSH}" \
     NODE_AGENT_MIRROR_SSH_PASS="${NODE_AGENT_MIRROR_SSH_PASS:-}" \
     NODE_AGENT_IMAGE="${NODE_AGENT_IMAGE:-nexuspanel/node:latest}" \
     APP_DIR="${APP_DIR}" \
     bash "$script"; then
    ok "Iran agent mirror synced."
  else
    warn "Iran agent mirror sync failed (IR node provision may stay slow until fixed)."
  fi
}

cmd_update()  {
  need_root
  fetch_repo
  seed_data_dir
  ensure_runtime_env
  ensure_docker_gid
  ensure_code_permissions
  ensure_data_permissions
  load_env_creds
  disable_conflicting_services
  configure_firewall
  install_cli
  # Before container swap: patch nginx so clients never see stock 502.
  ensure_nginx_restarting_page
  compose up -d --build
  # Autostart policy does not revive a container left stopped by a failed swap.
  compose start "${APP_NAME}" >/dev/null 2>&1 || true
  ensure_nginx_restarting_page
  wait_for_panel
  write_install_meta
  sync_agent_github_if_configured
  sync_agent_mirror_if_configured
  ok "Updated."
  print_access
}
cmd_up()      { need_root; compose up -d; ok "Started."; }
cmd_down()    { need_root; compose down; ok "Stopped."; }
cmd_restart() {
  need_root
  ensure_nginx_restarting_page
  compose restart
  ok "Restarted."
}
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
${BOLD}${BRAND}NEXUS${NC} ${BOLD}PANEL${NC}  ${MUTED}host manager${NC}

Usage: ${APP_NAME} <command>

  install            Install via branded shell wizard (WEB_WIZARD=1 for browser)
  update             Pull latest and rebuild
  up | down | restart
  status             Show container status
  info               Show panel URL, admin login, and paths
  https              Set up / refresh nginx TLS (DOMAIN=… EMAIL=… optional)
  check | doctor     Check dashboard/API locally and firewall hints
  logs               Tail logs
  backup             Create a backup archive
  restore <file>     Restore from a backup archive
  cli <args...>      Run nexuspanel-cli inside the container
  uninstall          Remove the app (keeps data dir)

Also: ${BOLD}nexus${NC}  — interactive management console (status, SSL, geo, admins, …)
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
    https|tls) cmd_https "$@";;
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
