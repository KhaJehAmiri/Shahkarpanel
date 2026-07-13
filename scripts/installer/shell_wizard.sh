#!/usr/bin/env bash
# NexusPanel shell installer wizard — branded host console (EN/FA).
# Invoked by: nexuspanel.sh install → run_install_wizard
set -euo pipefail

CONFIG_PATH=""
DATA_DIR="${DATA_DIR:-/var/lib/nexuspanel}"

# Brand palette (matches dashboard --nx-accent / console `nexus`)
if [ -t 1 ] || [ -t 2 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_RED=$'\033[0;31m'; C_YELLOW=$'\033[0;33m'; C_WHITE=$'\033[0;37m'
  C_BRAND=$'\033[38;5;80m'      # teal
  C_BRAND_DIM=$'\033[38;5;73m'
  C_INDIGO=$'\033[38;5;105m'
  C_MUTED=$'\033[38;5;245m'
  C_OK=$'\033[38;5;78m'
  C_BAD=$'\033[38;5;203m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_YELLOW=""; C_WHITE=""
  C_BRAND=""; C_BRAND_DIM=""; C_INDIGO=""; C_MUTED=""; C_OK=""; C_BAD=""
fi

# Install config (defaults)
PANEL_DEFAULT_LANG="en"
INSTALLER_UI_LANG="en"
DOMAIN=""
EMAIL=""
SKIP_HTTPS="0"
AUTO_CREDENTIALS="1"
ADMIN_USERNAME=""
ADMIN_PASSWORD=""
DASHBOARD_PATH=""
PANEL_TITLE="NexusPanel"
PRIMARY_COLOR="#2ee0c4"
SUPPORT_URL=""
PANEL_PORT="8000"
SKIP_NODE_BUILD="0"
CONFIGURE_FIREWALL="1"
PUBLIC_IP=""
RAM_MB=""
DOCKER_OK="0"
STEP_N=0
STEP_TOTAL=7

rand_path() {
  head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16
}

rand_secret() {
  head -c 48 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c "${1:-24}"
}

# Read from terminal even when script is piped: bash <(curl ...) install
ui_read() {
  local prompt="$1"
  local var="$2"
  if [ -t 0 ]; then
    read -r -p "$prompt" "$var" || true
  else
    read -r -p "$prompt" "$var" </dev/tty || true
  fi
}

ui_read_secret() {
  local prompt="$1"
  local var="$2"
  if [ -t 0 ]; then
    read -r -s -p "$prompt" "$var" || true
    echo
  else
    read -r -s -p "$prompt" "$var" </dev/tty || true
    echo
  fi
}

ui_clear() {
  printf '\033[2J\033[H' >/dev/tty 2>/dev/null || clear 2>/dev/null || true
}

nx_ok()   { printf "%b✓%b %s\n" "$C_OK" "$C_RESET" "$*"; }
nx_warn() { printf "%b!%b %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
nx_err()  { printf "%b✗%b %s\n" "$C_BAD" "$C_RESET" "$*" >&2; }
nx_info() { printf "%b›%b %s\n" "$C_BRAND" "$C_RESET" "$*"; }

nx_prompt() {
  printf "%b›%b %b%s%b " "$C_BRAND" "$C_RESET" "$C_WHITE" "$1" "$C_RESET"
}

ui_confirm() {
  local prompt="${1:-Continue?}" default="${2:-y}" ans=""
  local hint="y/N"
  case "$default" in y|Y) hint="Y/n" ;; esac
  nx_prompt "${prompt} [${hint}]"
  if [ -t 0 ]; then read -r ans || true; else read -r ans </dev/tty || true; fi
  ans="${ans:-$default}"
  [[ "$ans" =~ ^[Yy] ]]
}

nx_banner() {
  ui_clear
  printf "\n"
  printf "%b" "$C_BRAND"
  cat <<'EOF'
      ╭──╮
   ◆──┤ NX ├──◆
      ╰──╯
EOF
  printf "%b" "$C_RESET"
  printf "  %bNEXUS%b %bPANEL%b  %binstaller%b  %b·%b  %bv1%b\n" \
    "${C_BOLD}${C_BRAND}" "$C_RESET" \
    "${C_BOLD}${C_WHITE}" "$C_RESET" \
    "$C_MUTED" "$C_RESET" \
    "$C_MUTED" "$C_RESET" \
    "$C_BRAND_DIM" "$C_RESET"
  printf "%b  ──────────────────────────────────────────────%b\n" "$C_MUTED" "$C_RESET"
  printf "  %b●%b %-10s %b%s%b\n" "$C_BRAND" "$C_RESET" "Server IP" "$C_OK" "${PUBLIC_IP}" "$C_RESET"
  printf "  %b●%b %-10s %b%s MB%b\n" "$C_BRAND" "$C_RESET" "Memory" "$C_OK" "${RAM_MB}" "$C_RESET"
  if [ "$DOCKER_OK" = "1" ]; then
    printf "  %b●%b %-10s %bOK%b\n" "$C_BRAND" "$C_RESET" "Docker" "$C_OK" "$C_RESET"
  else
    printf "  %b○%b %-10s %bwill install%b\n" "$C_YELLOW" "$C_RESET" "Docker" "$C_YELLOW" "$C_RESET"
  fi
  printf "%b  ──────────────────────────────────────────────%b\n\n" "$C_MUTED" "$C_RESET"
}

nx_section() {
  STEP_N=$((STEP_N + 1))
  printf "\n"
  printf "  %b◆%b %b%s%b  %b(%s/%s)%b\n" \
    "$C_BRAND" "$C_RESET" \
    "${C_BOLD}${C_WHITE}" "$1" "$C_RESET" \
    "$C_MUTED" "$STEP_N" "$STEP_TOTAL" "$C_RESET"
  [ -n "${2:-}" ] && printf "  %b│%b  %b%s%b\n" "$C_BRAND_DIM" "$C_RESET" "$C_MUTED" "$2" "$C_RESET"
  printf "\n"
}

nx_opt() {
  printf "  %b│%b  %b%2s%b  %s\n" "$C_BRAND_DIM" "$C_RESET" "$C_BRAND" "$1" "$C_RESET" "$2"
}

nx_kv() {
  printf "  %b│%b  %-18s %b%s%b\n" "$C_BRAND_DIM" "$C_RESET" "$1" "$C_BRAND" "$2" "$C_RESET"
}

detect_preflight() {
  RAM_MB=4096
  if [ -r /proc/meminfo ]; then
    RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  fi
  PUBLIC_IP="$(curl -fsSL --max-time 6 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$PUBLIC_IP" ] || PUBLIC_IP="127.0.0.1"
  if docker version >/dev/null 2>&1; then DOCKER_OK="1"; else DOCKER_OK="0"; fi
  if [ "$RAM_MB" -lt 3500 ]; then SKIP_NODE_BUILD="1"; fi
}

msg() {
  case "$INSTALLER_UI_LANG" in
    fa)
      case "$1" in
        choose_lang) echo "زبان نصب‌کننده" ;;
        choose_lang_d) echo "زبان منوی نصب را انتخاب کنید" ;;
        panel_lang) echo "زبان پنل" ;;
        panel_lang_d) echo "زبان پیش‌فرض داشبورد ادمین" ;;
        net) echo "شبکه و HTTPS" ;;
        net_d) echo "دامنه برای SSL — خالی = گواهی روی IP" ;;
        domain_p) echo "دامنه (Enter = خالی)" ;;
        email_p) echo "ایمیل Let's Encrypt (اختیاری)" ;;
        skip_https) echo "HTTPS را رد کنم؟ (فقط HTTP)" ;;
        admin) echo "حساب ادمین" ;;
        admin_d) echo "اطلاعات sudo — فقط یک‌بار بعد از نصب نمایش داده می‌شود" ;;
        auto_creds) echo "نام کاربری و رمز تصادفی ساخته شود؟" ;;
        user_p) echo "نام کاربری ادمین" ;;
        pass_p) echo "رمز عبور ادمین" ;;
        dash_p) echo "مسیر مخفی داشبورد (Enter = خودکار)" ;;
        brand) echo "برندینگ" ;;
        brand_d) echo "اختیاری — می‌توانید بعداً از پنل تغییر دهید" ;;
        title_p) echo "عنوان پنل [NexusPanel]" ;;
        color_p) echo "رنگ اصلی [#2ee0c4]" ;;
        support_p) echo "لینک پشتیبانی (اختیاری)" ;;
        adv) echo "تنظیمات پیشرفته" ;;
        adv_d) echo "پورت، ایمیج نود، فایروال" ;;
        port_p) echo "پورت داخلی پنل [8000]" ;;
        skip_node) echo "رد کردن build ایمیج node-agent؟ (نصب سریع‌تر)" ;;
        ufw) echo "تنظیم فایروال UFW؟" ;;
        review) echo "بررسی نهایی" ;;
        review_d) echo "تأیید کنید تا نصب شروع شود" ;;
        start) echo "شروع نصب؟" ;;
        cancelled) echo "نصب لغو شد." ;;
        saved) echo "تنظیمات ذخیره شد — نصب در حال شروع…" ;;
        choose) echo "انتخاب کنید" ;;
        *) echo "$1" ;;
      esac
      ;;
    *)
      case "$1" in
        choose_lang) echo "Installer language" ;;
        choose_lang_d) echo "Language for this installer UI" ;;
        panel_lang) echo "Panel language" ;;
        panel_lang_d) echo "Default language for the admin dashboard" ;;
        net) echo "Network & HTTPS" ;;
        net_d) echo "Domain for SSL — empty = IP certificate" ;;
        domain_p) echo "Domain (Enter to skip)" ;;
        email_p) echo "Let's Encrypt email (optional)" ;;
        skip_https) echo "Skip HTTPS setup? (HTTP only)" ;;
        admin) echo "Admin account" ;;
        admin_d) echo "Sudo credentials — shown once after install" ;;
        auto_creds) echo "Generate random username & password?" ;;
        user_p) echo "Admin username" ;;
        pass_p) echo "Admin password" ;;
        dash_p) echo "Secret dashboard path (Enter = auto)" ;;
        brand) echo "Branding" ;;
        brand_d) echo "Optional — you can change this later in the panel" ;;
        title_p) echo "Panel title [NexusPanel]" ;;
        color_p) echo "Primary color [#2ee0c4]" ;;
        support_p) echo "Support URL (optional)" ;;
        adv) echo "Advanced options" ;;
        adv_d) echo "Port, node image, firewall" ;;
        port_p) echo "Internal panel port [8000]" ;;
        skip_node) echo "Skip node-agent image build? (faster install)" ;;
        ufw) echo "Configure UFW firewall?" ;;
        review) echo "Review & install" ;;
        review_d) echo "Confirm settings to begin installation" ;;
        start) echo "Start installation?" ;;
        cancelled) echo "Installation cancelled." ;;
        saved) echo "Configuration saved — starting install…" ;;
        choose) echo "Choose" ;;
        *) echo "$1" ;;
      esac
      ;;
  esac
}

step_ui_language() {
  nx_section "$(msg choose_lang)" "$(msg choose_lang_d)"
  nx_opt "1" "English"
  nx_opt "2" "فارسی"
  echo
  local c=""
  nx_prompt "$(msg choose) [1-2]"
  if [ -t 0 ]; then read -r c || true; else read -r c </dev/tty || true; fi
  case "${c:-1}" in
    2|fa|FA) INSTALLER_UI_LANG="fa" ;;
    *) INSTALLER_UI_LANG="en" ;;
  esac
  nx_ok "UI: ${INSTALLER_UI_LANG}"
}

step_panel_language() {
  nx_section "$(msg panel_lang)" "$(msg panel_lang_d)"
  nx_opt "1" "English"
  nx_opt "2" "فارسی (Persian)"
  nx_opt "3" "Русский (Russian)"
  nx_opt "4" "中文 (Chinese)"
  echo
  local c=""
  nx_prompt "$(msg choose) [1-4]"
  if [ -t 0 ]; then read -r c || true; else read -r c </dev/tty || true; fi
  case "${c:-1}" in
    2|fa) PANEL_DEFAULT_LANG="fa" ;;
    3|ru) PANEL_DEFAULT_LANG="ru" ;;
    4|zh) PANEL_DEFAULT_LANG="zh" ;;
    *) PANEL_DEFAULT_LANG="en" ;;
  esac
  nx_ok "Language: ${PANEL_DEFAULT_LANG}"
}

step_network() {
  nx_section "$(msg net)" "$(msg net_d)"
  nx_prompt "$(msg domain_p)"
  if [ -t 0 ]; then read -r DOMAIN || true; else read -r DOMAIN </dev/tty || true; fi
  DOMAIN="${DOMAIN// /}"
  if [ -n "$DOMAIN" ]; then
    nx_prompt "$(msg email_p)"
    if [ -t 0 ]; then read -r EMAIL || true; else read -r EMAIL </dev/tty || true; fi
    EMAIL="${EMAIL// /}"
  fi
  echo
  if ui_confirm "$(msg skip_https)" "n"; then
    SKIP_HTTPS="1"
    nx_warn "HTTPS disabled — not recommended for production"
  else
    SKIP_HTTPS="0"
    if [ -n "$DOMAIN" ]; then
      nx_ok "HTTPS: Let's Encrypt for ${DOMAIN}"
    else
      nx_ok "HTTPS: IP certificate for ${PUBLIC_IP}"
    fi
  fi
}

step_admin() {
  nx_section "$(msg admin)" "$(msg admin_d)"
  if ui_confirm "$(msg auto_creds)" "y"; then
    AUTO_CREDENTIALS="1"
    ADMIN_USERNAME=""
    ADMIN_PASSWORD=""
    nx_ok "Credentials: auto-generated"
  else
    AUTO_CREDENTIALS="0"
    nx_prompt "$(msg user_p)"
    if [ -t 0 ]; then read -r ADMIN_USERNAME || true; else read -r ADMIN_USERNAME </dev/tty || true; fi
    ui_read_secret "$(printf '%b›%b %b%s%b ' "$C_BRAND" "$C_RESET" "$C_WHITE" "$(msg pass_p)" "$C_RESET")" ADMIN_PASSWORD
    [ -n "$ADMIN_USERNAME" ] || ADMIN_USERNAME="admin"
    [ -n "$ADMIN_PASSWORD" ] || ADMIN_PASSWORD="$(rand_secret 20)"
  fi
  echo
  DASHBOARD_PATH="/$(rand_path)/"
  nx_prompt "$(msg dash_p)"
  if [ -t 0 ]; then read -r DASHBOARD_PATH || true; else read -r DASHBOARD_PATH </dev/tty || true; fi
  DASHBOARD_PATH="${DASHBOARD_PATH// /}"
  if [ -z "$DASHBOARD_PATH" ]; then
    DASHBOARD_PATH="/$(rand_path)/"
  fi
  case "$DASHBOARD_PATH" in
    /*) ;;
    *) DASHBOARD_PATH="/${DASHBOARD_PATH}" ;;
  esac
  case "$DASHBOARD_PATH" in
    */) ;;
    *) DASHBOARD_PATH="${DASHBOARD_PATH}/" ;;
  esac
  nx_ok "Dashboard path: ${DASHBOARD_PATH}"
}

step_branding() {
  nx_section "$(msg brand)" "$(msg brand_d)"
  local t c s
  nx_prompt "$(msg title_p)"
  if [ -t 0 ]; then read -r t || true; else read -r t </dev/tty || true; fi
  [ -n "$t" ] && PANEL_TITLE="$t"
  nx_prompt "$(msg color_p)"
  if [ -t 0 ]; then read -r c || true; else read -r c </dev/tty || true; fi
  [ -n "$c" ] && PRIMARY_COLOR="$c"
  nx_prompt "$(msg support_p)"
  if [ -t 0 ]; then read -r s || true; else read -r s </dev/tty || true; fi
  SUPPORT_URL="${s// /}"
  nx_ok "${PANEL_TITLE} · ${PRIMARY_COLOR}"
}

step_advanced() {
  nx_section "$(msg adv)" "$(msg adv_d)"
  local p=""
  nx_prompt "$(msg port_p)"
  if [ -t 0 ]; then read -r p || true; else read -r p </dev/tty || true; fi
  if [ -n "$p" ] && [ "$p" -gt 0 ] 2>/dev/null; then
    PANEL_PORT="$p"
  fi
  if ui_confirm "$(msg skip_node)" "$([ "$SKIP_NODE_BUILD" = "1" ] && echo y || echo n)"; then
    SKIP_NODE_BUILD="1"
  else
    SKIP_NODE_BUILD="0"
  fi
  if ui_confirm "$(msg ufw)" "y"; then
    CONFIGURE_FIREWALL="1"
  else
    CONFIGURE_FIREWALL="0"
  fi
}

step_review() {
  nx_section "$(msg review)" "$(msg review_d)"
  nx_kv "Panel language" "${PANEL_DEFAULT_LANG}"
  if [ -n "$DOMAIN" ]; then
    nx_kv "Domain" "${DOMAIN}"
  else
    nx_kv "Domain" "IP cert (${PUBLIC_IP})"
  fi
  nx_kv "HTTPS" "$([ "$SKIP_HTTPS" = "1" ] && echo disabled || echo enabled)"
  if [ "$AUTO_CREDENTIALS" = "1" ]; then
    nx_kv "Admin" "auto-generated"
  else
    nx_kv "Admin user" "${ADMIN_USERNAME}"
  fi
  nx_kv "Dashboard path" "${DASHBOARD_PATH}"
  nx_kv "Panel title" "${PANEL_TITLE}"
  nx_kv "Accent color" "${PRIMARY_COLOR}"
  nx_kv "Panel port" "${PANEL_PORT}"
  nx_kv "Node image" "$([ "$SKIP_NODE_BUILD" = "1" ] && echo skip || echo build)"
  nx_kv "UFW firewall" "$([ "$CONFIGURE_FIREWALL" = "1" ] && echo yes || echo no)"
  printf "\n%b  · · · · · · · · · · · · · · · · · · · · · · · ·%b\n\n" "$C_MUTED" "$C_RESET"
  if ! ui_confirm "$(msg start)" "y"; then
    nx_err "$(msg cancelled)"
    exit 1
  fi
}

write_config() {
  mkdir -p "$(dirname "$CONFIG_PATH")"
  PANEL_DEFAULT_LANG="$PANEL_DEFAULT_LANG" INSTALLER_UI_LANG="$INSTALLER_UI_LANG" \
  DOMAIN="$DOMAIN" EMAIL="$EMAIL" SKIP_HTTPS="$SKIP_HTTPS" \
  ADMIN_USERNAME="$ADMIN_USERNAME" ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  AUTO_CREDENTIALS="$AUTO_CREDENTIALS" DASHBOARD_PATH="$DASHBOARD_PATH" \
  PANEL_TITLE="$PANEL_TITLE" PRIMARY_COLOR="$PRIMARY_COLOR" SUPPORT_URL="$SUPPORT_URL" \
  PANEL_PORT="$PANEL_PORT" SKIP_NODE_BUILD="$SKIP_NODE_BUILD" CONFIGURE_FIREWALL="$CONFIGURE_FIREWALL" \
  python3 - "$CONFIG_PATH" <<'PY'
import json, sys, os
path = sys.argv[1]
cfg = {
    "panel_default_lang": os.environ.get("PANEL_DEFAULT_LANG", "en"),
    "installer_ui_lang": os.environ.get("INSTALLER_UI_LANG", "en"),
    "domain": os.environ.get("DOMAIN", ""),
    "email": os.environ.get("EMAIL", ""),
    "skip_https": os.environ.get("SKIP_HTTPS", "0") == "1",
    "admin_username": os.environ.get("ADMIN_USERNAME", ""),
    "admin_password": os.environ.get("ADMIN_PASSWORD", ""),
    "auto_credentials": os.environ.get("AUTO_CREDENTIALS", "1") == "1",
    "dashboard_path": os.environ.get("DASHBOARD_PATH", ""),
    "panel_title": os.environ.get("PANEL_TITLE", "NexusPanel"),
    "primary_color": os.environ.get("PRIMARY_COLOR", "#2ee0c4"),
    "support_url": os.environ.get("SUPPORT_URL", ""),
    "panel_port": int(os.environ.get("PANEL_PORT", "8000") or 8000),
    "skip_node_build": os.environ.get("SKIP_NODE_BUILD", "0") == "1",
    "configure_firewall": os.environ.get("CONFIGURE_FIREWALL", "1") == "1",
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
PY
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --config) CONFIG_PATH="$2"; shift 2 ;;
      *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
  done
  [ -n "$CONFIG_PATH" ] || { echo "--config required" >&2; exit 2; }

  detect_preflight
  nx_banner
  step_ui_language
  step_panel_language
  step_network
  step_admin
  step_branding
  step_advanced
  step_review

  export PANEL_DEFAULT_LANG INSTALLER_UI_LANG DOMAIN EMAIL SKIP_HTTPS
  export AUTO_CREDENTIALS ADMIN_USERNAME ADMIN_PASSWORD DASHBOARD_PATH
  export PANEL_TITLE PRIMARY_COLOR SUPPORT_URL PANEL_PORT SKIP_NODE_BUILD CONFIGURE_FIREWALL

  write_config
  echo
  nx_ok "$(msg saved)"
  echo
}

main "$@"
