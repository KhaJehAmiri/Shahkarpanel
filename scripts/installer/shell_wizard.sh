#!/usr/bin/env bash
# NexusPanel shell installer wizard — 3x-ui style (clean menus, no browser/curses).
set -euo pipefail

CONFIG_PATH=""
DATA_DIR="${DATA_DIR:-/var/lib/nexuspanel}"

# 3x-ui style colours
red=$'\033[0;31m'
green=$'\033[0;32m'
blue=$'\033[0;34m'
yellow=$'\033[0;33m'
cyan=$'\033[0;36m'
bold=$'\033[1m'
plain=$'\033[0m'

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
PRIMARY_COLOR="#5b8cff"
SUPPORT_URL=""
PANEL_PORT="8000"
SKIP_NODE_BUILD="0"
CONFIGURE_FIREWALL="1"
PUBLIC_IP=""
RAM_MB=""
DOCKER_OK="0"

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

ui_hr() {
  echo -e "${green}══════════════════════════════════════════════════════════════${plain}"
}

ui_title() {
  ui_hr
  echo -e "${green}  $*${plain}"
  ui_hr
}

ui_ok()   { echo -e "${green}✓${plain} $*"; }
ui_warn() { echo -e "${yellow}!${plain} $*"; }
ui_err()  { echo -e "${red}✗${plain} $*" >&2; }
ui_info() { echo -e "${blue}→${plain} $*"; }

ui_confirm() {
  local prompt="${1:-Continue?}" default="${2:-y}" ans=""
  ui_read "$(echo -e "${yellow}${prompt}${plain} [${default}]: ")" ans
  ans="${ans:-$default}"
  [[ "$ans" =~ ^[Yy] ]]
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

show_banner() {
  ui_clear
  echo -e "${cyan}${bold}"
  cat <<'BANNER'
    _   __                      ____            _
   / | / /__  ____ ___  ___   / __ \___  _____(_)___ _____
  /  |/ / _ \/ __ `__ \/ _ \ / /_/ / _ \/ ___/ / __ `/ __ \
 / /|  /  __/ / / / / /  __// ____/  __/ /  / / /_/ / / / /
/_/ |_/\___/_/ /_/ /_/\___//_/    \___/_/  /_/\__,_/_/ /_/
BANNER
  echo -e "${plain}"
  echo -e "  ${bold}NexusPanel${plain} — ${cyan}Professional VPN Control Plane${plain}"
  echo
  ui_hr
  echo -e "  ${blue}Server IP${plain}   : ${green}${PUBLIC_IP}${plain}"
  echo -e "  ${blue}Memory${plain}      : ${green}${RAM_MB} MB${plain}"
  echo -e "  ${blue}Docker${plain}      : $([ "$DOCKER_OK" = "1" ] && echo -e "${green}OK${plain}" || echo -e "${yellow}not ready${plain}")"
  ui_hr
  echo
}

step_ui_language() {
  ui_title "Installer language / زبان نصب"
  echo -e "  ${green}1.${plain} English"
  echo -e "  ${green}2.${plain} فارسی"
  echo
  local c=""
  ui_read "$(echo -e "${green}Choose [1-2, default 1]: ${plain}")" c
  case "${c:-1}" in
    2|fa|FA) INSTALLER_UI_LANG="fa" ;;
    *) INSTALLER_UI_LANG="en" ;;
  esac
}

msg() {
  case "$INSTALLER_UI_LANG" in
    fa)
      case "$1" in
        panel_lang) echo "زبان پنل" ;;
        panel_lang_d) echo "زبان پیش‌فرض داشبورد ادمین" ;;
        net) echo "شبکه و HTTPS" ;;
        net_d) echo "دامنه برای SSL یا خالی = گواهی IP" ;;
        domain_p) echo "دامنه (Enter = خالی): " ;;
        email_p) echo "ایمیل Let's Encrypt (اختیاری): " ;;
        skip_https) echo "HTTPS را رد کنم؟ (HTTP فقط)" ;;
        admin) echo "حساب ادمین" ;;
        admin_d) echo "اطلاعات sudo — یک‌بار بعد از نصب نمایش داده می‌شود" ;;
        auto_creds) echo "نام کاربری و رمز تصادفی تولید شود؟" ;;
        user_p) echo "نام کاربری ادمین: " ;;
        pass_p) echo "رمز عبور ادمین: " ;;
        dash_p) echo "مسیر مخفی داشبورد (Enter = خودکار): " ;;
        brand) echo "برندینگ (اختیاری)" ;;
        title_p) echo "عنوان پنل [NexusPanel]: " ;;
        color_p) echo "رنگ اصلی [#5b8cff]: " ;;
        support_p) echo "لینک پشتیبانی (اختیاری): " ;;
        adv) echo "تنظیمات پیشرفته" ;;
        port_p) echo "پورت داخلی پنل [8000]: " ;;
        skip_node) echo "رد کردن build ایمیج node-agent؟ (نصب سریع‌تر)" ;;
        ufw) echo "تنظیم فایروال UFW؟" ;;
        review) echo "بررسی نهایی" ;;
        review_d) echo "تأیید کنید و نصب شروع می‌شود" ;;
        start) echo "شروع نصب؟" ;;
        cancelled) echo "نصب لغو شد." ;;
        saved) echo "تنظیمات ذخیره شد — نصب در حال شروع…" ;;
        *) echo "$1" ;;
      esac
      ;;
    *)
      case "$1" in
        panel_lang) echo "Panel language" ;;
        panel_lang_d) echo "Default language for admin dashboard" ;;
        net) echo "Network & HTTPS" ;;
        net_d) echo "Domain for SSL, or empty = IP certificate" ;;
        domain_p) echo "Domain (Enter to skip): " ;;
        email_p) echo "Let's Encrypt email (optional): " ;;
        skip_https) echo "Skip HTTPS setup? (HTTP only)" ;;
        admin) echo "Admin account" ;;
        admin_d) echo "Sudo credentials — shown once after install" ;;
        auto_creds) echo "Generate random username & password?" ;;
        user_p) echo "Admin username: " ;;
        pass_p) echo "Admin password: " ;;
        dash_p) echo "Secret dashboard path (Enter = auto): " ;;
        brand) echo "Branding (optional)" ;;
        title_p) echo "Panel title [NexusPanel]: " ;;
        color_p) echo "Primary color [#5b8cff]: " ;;
        support_p) echo "Support URL (optional): " ;;
        adv) echo "Advanced options" ;;
        port_p) echo "Internal panel port [8000]: " ;;
        skip_node) echo "Skip node-agent image build? (faster install)" ;;
        ufw) echo "Configure UFW firewall?" ;;
        review) echo "Review & install" ;;
        review_d) echo "Confirm settings to begin installation" ;;
        start) echo "Start installation?" ;;
        cancelled) echo "Installation cancelled." ;;
        saved) echo "Configuration saved — starting install…" ;;
        *) echo "$1" ;;
      esac
      ;;
  esac
}

step_panel_language() {
  echo
  ui_title "$(msg panel_lang)"
  ui_info "$(msg panel_lang_d)"
  echo
  echo -e "  ${green}1.${plain} English"
  echo -e "  ${green}2.${plain} فارسی (Persian)"
  echo -e "  ${green}3.${plain} Русский (Russian)"
  echo -e "  ${green}4.${plain} 中文 (Chinese)"
  echo
  local c=""
  ui_read "$(echo -e "${green}Choose [1-4, default 1]: ${plain}")" c
  case "${c:-1}" in
    2|fa) PANEL_DEFAULT_LANG="fa" ;;
    3|ru) PANEL_DEFAULT_LANG="ru" ;;
    4|zh) PANEL_DEFAULT_LANG="zh" ;;
    *) PANEL_DEFAULT_LANG="en" ;;
  esac
  ui_ok "Language: ${PANEL_DEFAULT_LANG}"
}

step_network() {
  echo
  ui_title "$(msg net)"
  ui_info "$(msg net_d)"
  echo
  ui_read "$(echo -e "${green}$(msg domain_p)${plain}")" DOMAIN
  DOMAIN="${DOMAIN// /}"
  if [ -n "$DOMAIN" ]; then
    ui_read "$(echo -e "${green}$(msg email_p)${plain}")" EMAIL
    EMAIL="${EMAIL// /}"
  fi
  echo
  if ui_confirm "$(msg skip_https)" "n"; then
    SKIP_HTTPS="1"
    ui_warn "HTTPS disabled — not recommended for production"
  else
    SKIP_HTTPS="0"
    if [ -n "$DOMAIN" ]; then
      ui_ok "HTTPS: Let's Encrypt for ${DOMAIN}"
    else
      ui_ok "HTTPS: IP certificate for ${PUBLIC_IP}"
    fi
  fi
}

step_admin() {
  echo
  ui_title "$(msg admin)"
  ui_info "$(msg admin_d)"
  echo
  if ui_confirm "$(msg auto_creds)" "y"; then
    AUTO_CREDENTIALS="1"
    ADMIN_USERNAME=""
    ADMIN_PASSWORD=""
    ui_ok "Credentials: auto-generated"
  else
    AUTO_CREDENTIALS="0"
    ui_read "$(echo -e "${green}$(msg user_p)${plain}")" ADMIN_USERNAME
    ui_read_secret "$(echo -e "${green}$(msg pass_p)${plain}")" ADMIN_PASSWORD
    [ -n "$ADMIN_USERNAME" ] || ADMIN_USERNAME="admin"
    [ -n "$ADMIN_PASSWORD" ] || ADMIN_PASSWORD="$(rand_secret 20)"
  fi
  echo
  DASHBOARD_PATH="/$(rand_path)/"
  ui_read "$(echo -e "${green}$(msg dash_p)${plain}")" DASHBOARD_PATH
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
  ui_ok "Dashboard path: ${DASHBOARD_PATH}"
}

step_branding() {
  echo
  ui_title "$(msg brand)"
  local t c s
  ui_read "$(echo -e "${green}$(msg title_p)${plain}")" t
  [ -n "$t" ] && PANEL_TITLE="$t"
  ui_read "$(echo -e "${green}$(msg color_p)${plain}")" c
  [ -n "$c" ] && PRIMARY_COLOR="$c"
  ui_read "$(echo -e "${green}$(msg support_p)${plain}")" s
  SUPPORT_URL="${s// /}"
}

step_advanced() {
  echo
  ui_title "$(msg adv)"
  local p=""
  ui_read "$(echo -e "${green}$(msg port_p)${plain}")" p
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
  echo
  ui_title "$(msg review)"
  ui_info "$(msg review_d)"
  echo
  echo -e "  ${blue}Panel language${plain}  : ${green}${PANEL_DEFAULT_LANG}${plain}"
  if [ -n "$DOMAIN" ]; then
    echo -e "  ${blue}Domain${plain}           : ${green}${DOMAIN}${plain}"
  else
    echo -e "  ${blue}Domain${plain}           : ${yellow}IP cert (${PUBLIC_IP})${plain}"
  fi
  echo -e "  ${blue}HTTPS${plain}            : $([ "$SKIP_HTTPS" = "1" ] && echo -e "${yellow}disabled${plain}" || echo -e "${green}enabled${plain}")"
  if [ "$AUTO_CREDENTIALS" = "1" ]; then
    echo -e "  ${blue}Admin${plain}            : ${green}auto-generated${plain}"
  else
    echo -e "  ${blue}Admin user${plain}       : ${green}${ADMIN_USERNAME}${plain}"
  fi
  echo -e "  ${blue}Dashboard path${plain}   : ${green}${DASHBOARD_PATH}${plain}"
  echo -e "  ${blue}Panel title${plain}      : ${green}${PANEL_TITLE}${plain}"
  echo -e "  ${blue}Panel port${plain}       : ${green}${PANEL_PORT}${plain}"
  echo -e "  ${blue}Node image build${plain} : $([ "$SKIP_NODE_BUILD" = "1" ] && echo -e "${yellow}skip${plain}" || echo -e "${green}yes${plain}")"
  echo -e "  ${blue}UFW firewall${plain}     : $([ "$CONFIGURE_FIREWALL" = "1" ] && echo -e "${green}yes${plain}" || echo -e "${yellow}no${plain}")"
  echo
  ui_hr
  if ! ui_confirm "$(msg start)" "y"; then
    ui_err "$(msg cancelled)"
    exit 1
  fi
}

write_config() {
  mkdir -p "$(dirname "$CONFIG_PATH")"
  python3 - "$CONFIG_PATH" <<PY
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
    "primary_color": os.environ.get("PRIMARY_COLOR", "#5b8cff"),
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
  show_banner
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
  ui_ok "$(msg saved)"
  echo
}

main "$@"
