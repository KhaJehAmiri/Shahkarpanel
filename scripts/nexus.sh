#!/usr/bin/env bash
# NexusPanel host management console (x-ui / 3X-UI style menu).
#
# Invoked on the panel HOST as `nexus`. Drives the docker-compose deployment
# (or a systemd deployment as a fallback) and proxies admin management to the
# in-container `nexuspanel-cli`. Bilingual (English / فارسی). Every destructive
# action asks for confirmation.
set -uo pipefail

# --------------------------------------------------------------------------
# Configuration / discovery
# --------------------------------------------------------------------------
APP_DIR="${NEXUS_APP_DIR:-/opt/nexuspanel}"
DATA_DIR="${NEXUS_DATA_DIR:-/var/lib/nexuspanel}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-nexuspanel}"
SERVICE="nexuspanel"          # compose service name AND systemd unit name
GIT_BRANCH_DEFAULT="master"
LANG_FILE="${NEXUS_LANG_FILE:-$DATA_DIR/.nexus-lang}"
NEXUS_LANG="en"

GEOIP_URL="https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat"
GEOSITE_URL="https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat"

if [ -t 1 ]; then
  C_RESET="\033[0m"; C_DIM="\033[2m"; C_BOLD="\033[1m"
  C_RED="\033[0;31m"; C_GREEN="\033[0;32m"; C_YELLOW="\033[0;33m"
  C_BLUE="\033[0;34m"; C_CYAN="\033[0;36m"; C_MAGENTA="\033[0;35m"
  C_WHITE="\033[0;37m"
  # Brand palette (matches dashboard --nx-accent / --nx-accent-2)
  C_BRAND="\033[38;5;80m"       # teal #2ee0c4-ish
  C_BRAND_DIM="\033[38;5;73m"   # softer teal
  C_INDIGO="\033[38;5;105m"     # indigo accent-2
  C_MUTED="\033[38;5;245m"      # faint text
  C_OK="\033[38;5;78m"          # soft green for Running
  C_BAD="\033[38;5;203m"        # soft red for Stopped
else
  C_RESET=""; C_DIM=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""
  C_BLUE=""; C_CYAN=""; C_MAGENTA=""; C_WHITE=""
  C_BRAND=""; C_BRAND_DIM=""; C_INDIGO=""; C_MUTED=""; C_OK=""; C_BAD=""
fi

msg()  { printf "%b\n" "$*"; }
ok()   { printf "%b\n" "${C_OK}$*${C_RESET}"; }
warn() { printf "%b\n" "${C_YELLOW}$*${C_RESET}"; }
err()  { printf "%b\n" "${C_BAD}$*${C_RESET}" >&2; }
hr()   { printf "%b\n" "${C_MUTED}  · · · · · · · · · · · · · · · · · · · · · · · ·${C_RESET}"; }

# ── Nexus brand UI primitives (NOT x-ui boxed clone) ──────────────────────
# Left accent rail + section headers with node mark (◆).

rail() { printf "%b│%b " "$C_BRAND" "$C_RESET"; }

nx_banner() {
  local ver; ver="$(panel_version)"
  printf "\n"
  printf "%b" "$C_BRAND"
  cat <<'EOF'
      ╭──╮
   ◆──┤ NX ├──◆
      ╰──╯
EOF
  printf "%b" "$C_RESET"
  printf "  %bNEXUS%b %bPANEL%b  %bhost console%b  %b·%b  %b%s%b  %b·%b  %bv%s%b\n" \
    "${C_BOLD}${C_BRAND}" "$C_RESET" \
    "${C_BOLD}${C_WHITE}" "$C_RESET" \
    "$C_MUTED" "$C_RESET" \
    "$C_MUTED" "$C_RESET" \
    "$C_INDIGO" "$NEXUS_LANG" "$C_RESET" \
    "$C_MUTED" "$C_RESET" \
    "$C_BRAND_DIM" "$ver" "$C_RESET"
  printf "%b  ──────────────────────────────────────────────%b\n" "$C_MUTED" "$C_RESET"
}

nx_section() {
  # $1 = section title
  printf "\n  %b◆%b %b%s%b\n" "$C_BRAND" "$C_RESET" "${C_BOLD}${C_WHITE}" "$1" "$C_RESET"
}

nx_opt() {
  # $1 = key (0-23 / L), $2 = label
  local num="$1" label="$2"
  printf "  %b│%b  %b%2s%b  %s\n" "$C_BRAND_DIM" "$C_RESET" "$C_BRAND" "$num" "$C_RESET" "$label"
}

nx_opt_exit() {
  printf "  %b│%b  %b%2s%b  %s\n" "$C_MUTED" "$C_RESET" "$C_MUTED" "$1" "$C_RESET" "$2"
}

nx_kv() {
  local key="$1" val="$2"
  printf "  %b│%b  %b%s%b  %b%s%b\n" "$C_BRAND_DIM" "$C_RESET" "$C_MUTED" "$key" "$C_RESET" "$C_BRAND" "$val" "$C_RESET"
}

nx_prompt() {
  printf "\n  %b›%b %b%s%b %b[0-23]%b %b›%b " \
    "$C_BRAND" "$C_RESET" \
    "$C_WHITE" "$(t select)" "$C_RESET" \
    "$C_MUTED" "$C_RESET" \
    "$C_BRAND" "$C_RESET"
}

# --------------------------------------------------------------------------
# i18n
# --------------------------------------------------------------------------
declare -A EN FA

EN[title]="NexusPanel"
FA[title]="NexusPanel"
EN[subtitle]="Host Management Console"
FA[subtitle]="کنسول مدیریت سرور"
EN[grp_install]="Install & Update"
FA[grp_install]="نصب و بروزرسانی"
EN[grp_config]="Configuration"
FA[grp_config]="پیکربندی"
EN[grp_service]="Service Control"
FA[grp_service]="کنترل سرویس"
EN[grp_autostart]="Autostart"
FA[grp_autostart]="اجرای خودکار"
EN[grp_network]="Network & TLS"
FA[grp_network]="شبکه و TLS"
EN[grp_admin]="Admin Accounts"
FA[grp_admin]="حساب‌های ادمین"
EN[grp_lang]="Language"
FA[grp_lang]="زبان"
EN[hub]="hub status"
FA[hub]="وضعیت هاب"

EN[m_install]="Install"
FA[m_install]="نصب"
EN[m_update]="Update"
FA[m_update]="بروزرسانی"
EN[m_update_menu]="Update script / menu"
FA[m_update_menu]="بروزرسانی اسکریپت / منو"
EN[m_uninstall]="Uninstall"
FA[m_uninstall]="حذف"
EN[m_reset_userpass]="Reset Username & Password"
FA[m_reset_userpass]="بازنشانی نام‌کاربری و رمز"
EN[m_reset_path]="Reset Dashboard Path"
FA[m_reset_path]="بازنشانی مسیر داشبورد"
EN[m_change_port]="Change Panel Port"
FA[m_change_port]="تغییر پورت پنل"
EN[m_view_settings]="View Current Settings"
FA[m_view_settings]="نمایش تنظیمات فعلی"
EN[m_start]="Start"
FA[m_start]="روشن کردن"
EN[m_stop]="Stop"
FA[m_stop]="خاموش کردن"
EN[m_restart]="Restart"
FA[m_restart]="ری‌استارت"
EN[m_restart_xray]="Restart Xray"
FA[m_restart_xray]="ری‌استارت Xray"
EN[m_status]="Check Status"
FA[m_status]="بررسی وضعیت"
EN[m_logs]="Logs Management"
FA[m_logs]="مدیریت لاگ‌ها"
EN[m_enable_auto]="Enable Autostart"
FA[m_enable_auto]="فعال‌سازی اجرای خودکار"
EN[m_disable_auto]="Disable Autostart"
FA[m_disable_auto]="غیرفعال‌سازی اجرای خودکار"
EN[m_ssl]="SSL Certificate (HTTPS)"
FA[m_ssl]="گواهی SSL (HTTPS)"
EN[m_firewall]="Firewall Management"
FA[m_firewall]="مدیریت فایروال"
EN[m_bbr]="Enable BBR"
FA[m_bbr]="فعال‌سازی BBR"
EN[m_geo]="Update Geo Files"
FA[m_geo]="بروزرسانی فایل‌های Geo"
EN[m_speedtest]="Speedtest"
FA[m_speedtest]="تست سرعت"
EN[m_create_admin]="Create Admin"
FA[m_create_admin]="ساخت ادمین"
EN[m_list_admins]="List Admins"
FA[m_list_admins]="لیست ادمین‌ها"
EN[m_exit]="Exit"
FA[m_exit]="خروج"
EN[m_lang]="Language / زبان"
FA[m_lang]="زبان / Language"

EN[f_panel]="Panel state"
FA[f_panel]="وضعیت پنل"
EN[f_autostart]="Autostart"
FA[f_autostart]="اجرای خودکار"
EN[f_xray]="Xray state"
FA[f_xray]="وضعیت Xray"
EN[f_version]="Version"
FA[f_version]="نسخه"
EN[running]="Running"
FA[running]="در حال اجرا"
EN[stopped]="Stopped"
FA[stopped]="متوقف"
EN[yes]="Yes"
FA[yes]="بله"
EN[no]="No"
FA[no]="خیر"
EN[unknown]="unknown"
FA[unknown]="نامشخص"

EN[select]="Please enter your selection"
FA[select]="لطفاً گزینهٔ خود را وارد کنید"
EN[invalid]="Invalid option"
FA[invalid]="گزینهٔ نامعتبر"
EN[press_enter]="Press Enter to continue..."
FA[press_enter]="برای ادامه Enter را بزنید..."
EN[need_root]="This action needs root. Re-run with: sudo nexus"
FA[need_root]="این عملیات به دسترسی root نیاز دارد. با sudo nexus اجرا کنید"
EN[done]="Done."
FA[done]="انجام شد."
EN[aborted]="Aborted."
FA[aborted]="لغو شد."
EN[confirm_suffix]="[y/N]"
FA[confirm_suffix]="[y/N]"

EN[ask_lang]="Choose language:"
FA[ask_lang]="زبان را انتخاب کنید:"
EN[lang_saved]="Language updated."
FA[lang_saved]="زبان بروزرسانی شد."

EN[p_admin_user]="Admin username"
FA[p_admin_user]="نام‌کاربری ادمین"
EN[p_editing_admin]="Editing admin"
FA[p_editing_admin]="ادمین در حال ویرایش"
EN[p_new_user]="New username (blank = keep)"
FA[p_new_user]="نام‌کاربری جدید (خالی = بدون تغییر)"
EN[p_new_pass]="New password (blank = keep)"
FA[p_new_pass]="رمز جدید (خالی = بدون تغییر)"
EN[p_confirm_pass]="Confirm password"
FA[p_confirm_pass]="تکرار رمز"
EN[pass_mismatch]="Passwords do not match."
FA[pass_mismatch]="رمزها یکسان نیستند."
EN[nothing_changed]="Nothing to change."
FA[nothing_changed]="چیزی برای تغییر نبود."
EN[user_required]="Username is required."
FA[user_required]="نام‌کاربری الزامی است."

EN[p_new_path]="New dashboard path (blank = random)"
FA[p_new_path]="مسیر جدید داشبورد (خالی = تصادفی)"
EN[p_new_port]="New panel port (1-65535)"
FA[p_new_port]="پورت جدید پنل (۱ تا ۶۵۵۳۵)"
EN[bad_port]="Invalid port."
FA[bad_port]="پورت نامعتبر."
EN[port_warn]="Note: if HTTPS/nginx is in front, re-run SSL setup after changing the port."
FA[port_warn]="توجه: اگر nginx/HTTPS جلوی پنل است، بعد از تغییر پورت تنظیمات SSL را دوباره اجرا کنید."
EN[restart_needed]="Restarting panel to apply changes..."
FA[restart_needed]="در حال ری‌استارت پنل برای اعمال تغییرات..."

EN[xray_killed]="Xray stopped; the panel health-check will restart it within seconds."
FA[xray_killed]="Xray متوقف شد؛ health-check پنل ظرف چند ثانیه دوباره آن را اجرا می‌کند."
EN[ssl_delegate]="Launching SSL/HTTPS setup..."
FA[ssl_delegate]="در حال اجرای تنظیمات SSL/HTTPS..."
EN[ssl_missing]="SSL helper not found. Run: nexuspanel https"
FA[ssl_missing]="ابزار SSL یافت نشد. اجرا کنید: nexuspanel https"
EN[bbr_done]="BBR enabled (net.ipv4.tcp_congestion_control=bbr)."
FA[bbr_done]="BBR فعال شد (net.ipv4.tcp_congestion_control=bbr)."
EN[geo_updating]="Downloading geoip.dat and geosite.dat into the panel..."
FA[geo_updating]="در حال دانلود geoip.dat و geosite.dat در پنل..."
EN[geo_done]="Geo files updated; restarting Xray."
FA[geo_done]="فایل‌های Geo بروزرسانی شد؛ Xray ری‌استارت می‌شود."
EN[geo_fail]="Geo file update failed."
FA[geo_fail]="بروزرسانی فایل‌های Geo ناموفق بود."
EN[speedtest_run]="Running speedtest (best-effort)..."
FA[speedtest_run]="در حال اجرای تست سرعت..."
EN[speedtest_missing]="No speedtest tool available and auto-install failed."
FA[speedtest_missing]="ابزار تست سرعت موجود نیست و نصب خودکار ناموفق بود."

EN[fw_title]="Firewall (UFW)"
FA[fw_title]="فایروال (UFW)"
EN[fw_missing]="ufw is not installed."
FA[fw_missing]="ufw نصب نیست."
EN[fw_install_ask]="Install ufw now?"
FA[fw_install_ask]="الان ufw نصب شود؟"
EN[port_nginx_updated]="Updated nginx proxy_pass to the new port."
FA[port_nginx_updated]="proxy_pass در nginx به پورت جدید بروزرسانی شد."
EN[port_nginx_manual]="Could not auto-update nginx; edit proxy_pass manually if HTTPS is enabled."
FA[port_nginx_manual]="بروزرسانی خودکار nginx ممکن نشد؛ اگر HTTPS فعال است proxy_pass را دستی اصلاح کنید."
EN[geo_via_host]="Downloading on host, then copying into the panel..."
FA[geo_via_host]="دانلود روی هاست و کپی به داخل پنل..."
EN[fw_1]="Show status"
FA[fw_1]="نمایش وضعیت"
EN[fw_2]="Allow a port"
FA[fw_2]="باز کردن یک پورت"
EN[fw_3]="Delete a port rule"
FA[fw_3]="حذف قانون یک پورت"
EN[fw_4]="Enable UFW"
FA[fw_4]="فعال‌سازی UFW"
EN[fw_back]="Back"
FA[fw_back]="بازگشت"
EN[fw_port]="Port (e.g. 443 or 443/tcp)"
FA[fw_port]="پورت (مثلاً 443 یا 443/tcp)"

EN[not_installed]="NexusPanel directory not found"
FA[not_installed]="پوشهٔ NexusPanel یافت نشد"
EN[uninstall_warn]="This will STOP and REMOVE the NexusPanel containers."
FA[uninstall_warn]="این کار کانتینرهای NexusPanel را متوقف و حذف می‌کند."
EN[uninstall_keep]="Your data in /var/lib/nexuspanel and code are kept unless you choose otherwise."
FA[uninstall_keep]="داده‌های شما در /var/lib/nexuspanel و کد نگه داشته می‌شوند مگر خلافش را انتخاب کنید."
EN[uninstall_data]="Also DELETE all panel DATA in /var/lib/nexuspanel? (IRREVERSIBLE)"
FA[uninstall_data]="همچنین همهٔ داده‌های پنل در /var/lib/nexuspanel حذف شود؟ (غیرقابل‌بازگشت)"
EN[uninstall_sure]="Are you ABSOLUTELY sure? This destroys users, configs and backups."
FA[uninstall_sure]="کاملاً مطمئن هستید؟ این کار کاربران، تنظیمات و بکاپ‌ها را نابود می‌کند."
EN[uninstall_bin]="Remove the 'nexus' command itself from this host?"
FA[uninstall_bin]="خود دستور 'nexus' هم از این سرور حذف شود؟"

t() { local k="$1" v=""; if [ "$NEXUS_LANG" = "fa" ]; then v="${FA[$k]:-}"; fi; [ -z "$v" ] && v="${EN[$k]:-$k}"; printf '%s' "$v"; }

load_lang() {
  [ -f "$LANG_FILE" ] && NEXUS_LANG="$(tr -d '[:space:]' < "$LANG_FILE" 2>/dev/null)"
  case "$NEXUS_LANG" in fa|en) ;; *) NEXUS_LANG="en" ;; esac
}
save_lang() {
  mkdir -p "$(dirname "$LANG_FILE")" 2>/dev/null || true
  printf '%s' "$1" > "$LANG_FILE" 2>/dev/null || true
  NEXUS_LANG="$1"
}

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
require_root() { [ "$(id -u)" -eq 0 ] || { err "$(t need_root)"; return 1; }; }

compose_file() {
  local f
  for f in docker-compose.postgres.yml docker-compose.yml; do
    [ -f "$APP_DIR/$f" ] && { printf '%s' "$f"; return 0; }
  done
  return 1
}

DEPLOY_MODE=""
detect_deploy_mode() {
  if command -v docker >/dev/null 2>&1 && compose_file >/dev/null 2>&1; then
    DEPLOY_MODE="docker"
  elif command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}\.service"; then
    DEPLOY_MODE="systemd"
  else
    DEPLOY_MODE=""
  fi
}

dc() {
  local cf; cf="$(compose_file)" || { err "No docker-compose file in $APP_DIR"; return 1; }
  ( cd "$APP_DIR" && docker compose -p "$COMPOSE_PROJECT" -f "$cf" "$@" )
}

panel_container() { dc ps -q "$SERVICE" 2>/dev/null | head -n1; }

git_branch() {
  local b
  b="$(cd "$APP_DIR" && git -c safe.directory="$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  [ -n "$b" ] && [ "$b" != "HEAD" ] && { printf '%s' "$b"; return; }
  printf '%s' "$GIT_BRANCH_DEFAULT"
}

panel_version() { [ -f "$APP_DIR/VERSION" ] && tr -d '[:space:]' < "$APP_DIR/VERSION" || printf '%s' "$(t unknown)"; }

panel_cli()     { case "$DEPLOY_MODE" in docker) dc exec -T "$SERVICE" nexuspanel-cli "$@";; systemd) ( cd "$APP_DIR" && python3 nexuspanel-cli.py "$@" );; *) return 1;; esac; }
panel_cli_tty() { case "$DEPLOY_MODE" in docker) dc exec "$SERVICE" nexuspanel-cli "$@";; systemd) ( cd "$APP_DIR" && python3 nexuspanel-cli.py "$@" );; *) return 1;; esac; }

pause() { printf "\n%b" "${C_DIM}$(t press_enter)${C_RESET}"; read -r _ || exit 0; }

confirm() {
  local ans
  printf "%b" "${C_YELLOW}$1 $(t confirm_suffix): ${C_RESET}"
  read -r ans
  case "$ans" in y|Y|yes|YES|بله) return 0 ;; *) return 1 ;; esac
}

# .env editing: set KEY=VALUE in the panel's repo .env (create/replace line).
env_file_path() { [ -f "$APP_DIR/.env" ] && printf '%s' "$APP_DIR/.env"; }

set_env_var() {
  local key="$1" val="$2" f; f="$(env_file_path)"
  [ -n "$f" ] || { err ".env not found in $APP_DIR"; return 1; }
  if grep -q "^${key}=" "$f" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$f"
  else
    printf '%s=%s\n' "$key" "$val" >> "$f"
  fi
}

get_env_var() {
  local key="$1" f; f="$(env_file_path)"
  [ -n "$f" ] || return 1
  sed -n "s/^${key}=//p" "$f" 2>/dev/null | head -n1
}

get_runtime_var() {
  local key="$1" f="$DATA_DIR/.env"
  [ -f "$f" ] || return 1
  sed -n "s/^${key}=//p" "$f" 2>/dev/null | head -n1
}

rand_path() { printf '/%s/' "$(head -c 16 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16)"; }

# --------------------------------------------------------------------------
# State (for footer)
# --------------------------------------------------------------------------
state_panel() {
  if [ "$DEPLOY_MODE" = "docker" ]; then
    local cid; cid="$(panel_container)"
    [ -n "$cid" ] && [ "$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)" = "running" ] && { printf 'run'; return; }
  elif [ "$DEPLOY_MODE" = "systemd" ]; then
    systemctl is-active "$SERVICE" >/dev/null 2>&1 && { printf 'run'; return; }
  fi
  printf 'stop'
}

state_autostart() {
  if [ "$DEPLOY_MODE" = "docker" ]; then
    local cid pol; cid="$(panel_container)"
    [ -n "$cid" ] && pol="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$cid" 2>/dev/null)"
    case "$pol" in always|unless-stopped|on-failure) printf 'yes'; return;; esac
  elif [ "$DEPLOY_MODE" = "systemd" ]; then
    systemctl is-enabled "$SERVICE" >/dev/null 2>&1 && { printf 'yes'; return; }
  fi
  printf 'no'
}

state_xray() {
  if [ "$DEPLOY_MODE" = "docker" ]; then
    dc exec -T "$SERVICE" pgrep -x xray </dev/null >/dev/null 2>&1 && { printf 'run'; return; }
  elif command -v pgrep >/dev/null 2>&1; then
    pgrep -x xray >/dev/null 2>&1 && { printf 'run'; return; }
  fi
  printf 'stop'
}

colorized_state() { # $1 = run|stop
  if [ "$1" = "run" ]; then printf "%b● %s%b" "$C_OK" "$(t running)" "$C_RESET"
  else printf "%b○ %s%b" "$C_BAD" "$(t stopped)" "$C_RESET"; fi
}
colorized_bool() {
  if [ "$1" = "yes" ]; then printf "%b● %s%b" "$C_OK" "$(t yes)" "$C_RESET"
  else printf "%b○ %s%b" "$C_YELLOW" "$(t no)" "$C_RESET"; fi
}

# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
action_install() {
  require_root || return 1
  if command -v nexuspanel >/dev/null 2>&1; then nexuspanel install; else err "$(t not_installed): nexuspanel manager missing"; fi
}

action_update() {
  require_root || return 1
  if command -v nexuspanel >/dev/null 2>&1; then
    nexuspanel update; return $?
  fi
  [ -d "$APP_DIR/.git" ] || { err "Not a git checkout."; return 1; }
  local branch; branch="$(git_branch)"
  ( cd "$APP_DIR" && git -c safe.directory="$APP_DIR" fetch origin "$branch" && git -c safe.directory="$APP_DIR" reset --hard "origin/${branch}" ) || return 1
  if [ "$DEPLOY_MODE" = "docker" ]; then dc up -d --build "$SERVICE"; else systemctl restart "$SERVICE"; fi
  ok "$(t done)"
}

action_update_menu() {
  require_root || return 1
  [ -d "$APP_DIR/.git" ] || { err "Not a git checkout."; return 1; }
  local branch; branch="$(git_branch)"
  ( cd "$APP_DIR" && git -c safe.directory="$APP_DIR" fetch origin "$branch" && git -c safe.directory="$APP_DIR" reset --hard "origin/${branch}" )
  if [ -f "$APP_DIR/scripts/install-nexus.sh" ]; then
    bash "$APP_DIR/scripts/install-nexus.sh"
  fi
  ok "$(t done)"
  exec "$0" "$@"
}

action_start()   { require_root || return 1; if [ "$DEPLOY_MODE" = "docker" ]; then dc up -d "$SERVICE"; else systemctl start "$SERVICE"; fi && ok "$(t done)"; }
action_stop()    { require_root || return 1; if [ "$DEPLOY_MODE" = "docker" ]; then dc stop "$SERVICE"; else systemctl stop "$SERVICE"; fi && ok "$(t done)"; }
action_restart() { require_root || return 1; if [ "$DEPLOY_MODE" = "docker" ]; then dc restart "$SERVICE"; else systemctl restart "$SERVICE"; fi && ok "$(t done)"; }

action_restart_xray() {
  require_root || return 1
  if [ "$DEPLOY_MODE" = "docker" ]; then
    dc exec -T -u 0 "$SERVICE" pkill -x xray 2>/dev/null || true
    # Health-check should bring it back; if jobs are stuck, fall back to a panel restart.
    local i
    for i in 1 2 3 4 5 6 7 8; do
      sleep 2
      if dc exec -T "$SERVICE" pgrep -x xray </dev/null >/dev/null 2>&1; then
        ok "$(t done)"
        return 0
      fi
    done
    warn "$(t xray_killed)"
    warn "$(t restart_needed)"
    dc restart "$SERVICE" && ok "$(t done)"
  else
    pkill -x xray 2>/dev/null || true
    sleep 2
    if pgrep -x xray >/dev/null 2>&1; then ok "$(t done)"; else systemctl restart "$SERVICE" && ok "$(t done)"; fi
  fi
}

action_logs() {
  if [ "$DEPLOY_MODE" = "docker" ]; then dc logs -f --tail 200 "$SERVICE"
  elif [ "$DEPLOY_MODE" = "systemd" ]; then journalctl -u "$SERVICE" -n 200 -f; fi
}

action_status() {
  hr
  msg "${C_BOLD}$(t f_panel):${C_RESET} $(colorized_state "$(state_panel)")   ${C_BOLD}$(t f_xray):${C_RESET} $(colorized_state "$(state_xray)")   ${C_BOLD}$(t f_version):${C_RESET} ${C_CYAN}$(panel_version)${C_RESET}"
  hr
  if [ "$DEPLOY_MODE" = "docker" ]; then dc ps
  elif [ "$DEPLOY_MODE" = "systemd" ]; then systemctl --no-pager --full status "$SERVICE" 2>&1 | head -n 15; fi
  local port; port="$(get_env_var UVICORN_PORT)"; port="${port:-8000}"
  if command -v curl >/dev/null 2>&1; then
    local code; code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "http://127.0.0.1:${port}/api/system/version" 2>/dev/null)"
    [ -n "$code" ] && msg "http 127.0.0.1:${port} -> ${C_CYAN}${code}${C_RESET}"
  fi
}

action_enable_auto() {
  require_root || return 1
  if [ "$DEPLOY_MODE" = "docker" ]; then
    local cid; cid="$(panel_container)"
    [ -n "$cid" ] && docker update --restart always "$cid" >/dev/null 2>&1 && ok "$(t done)"
  elif [ "$DEPLOY_MODE" = "systemd" ]; then systemctl enable "$SERVICE" && ok "$(t done)"; fi
}

action_disable_auto() {
  require_root || return 1
  if [ "$DEPLOY_MODE" = "docker" ]; then
    local cid; cid="$(panel_container)"
    [ -n "$cid" ] && docker update --restart no "$cid" >/dev/null 2>&1 && ok "$(t done)"
  elif [ "$DEPLOY_MODE" = "systemd" ]; then systemctl disable "$SERVICE" && ok "$(t done)"; fi
}

set_password_via_env() { # $1=username $2=password
  case "$DEPLOY_MODE" in
    docker)  dc exec -T -e "NEXUSPANEL_ADMIN_PASSWORD=$2" "$SERVICE" nexuspanel-cli admin set-password --username "$1" ;;
    systemd) ( cd "$APP_DIR" && NEXUSPANEL_ADMIN_PASSWORD="$2" python3 nexuspanel-cli.py admin set-password --username "$1" ) ;;
    *) return 1 ;;
  esac
}

action_reset_userpass() {
  require_root || return 1
  local u newu p p2
  # Auto-detect the sole sudo admin instead of asking the operator to type the
  # existing/previous username; only fall back to asking if that's ambiguous
  # (e.g. more than one sudo admin) or the panel isn't reachable yet.
  u="$(panel_cli admin whoami </dev/null 2>/dev/null | tr -d '\r\n')"
  if [ -n "$u" ]; then
    msg "$(t p_editing_admin): ${C_CYAN}${u}${C_RESET}"
  else
    printf "%b" "$(t p_admin_user): "; read -r u
    [ -n "$u" ] || { err "$(t user_required)"; return 1; }
  fi
  printf "%b" "$(t p_new_user): "; read -r newu
  printf "%b" "$(t p_new_pass): "; read -r -s p; echo
  local changed=0
  if [ -n "$p" ]; then
    printf "%b" "$(t p_confirm_pass): "; read -r -s p2; echo
    [ "$p" = "$p2" ] || { err "$(t pass_mismatch)"; return 1; }
    set_password_via_env "$u" "$p" && changed=1
  fi
  if [ -n "$newu" ] && [ "$newu" != "$u" ]; then
    panel_cli admin rename --current "$u" --new "$newu" && changed=1
  fi
  [ "$changed" -eq 1 ] || warn "$(t nothing_changed)"
}

action_reset_path() {
  require_root || return 1
  local p; printf "%b" "$(t p_new_path): "; read -r p
  [ -n "$p" ] || p="$(rand_path)"
  case "$p" in */) ;; *) p="${p}/" ;; esac
  case "$p" in /*) ;; *) p="/${p}" ;; esac
  set_env_var DASHBOARD_PATH "$p" || return 1
  ok "DASHBOARD_PATH=${p}"
  warn "$(t restart_needed)"; action_restart
}

action_change_port() {
  require_root || return 1
  local port old_port
  old_port="$(get_env_var UVICORN_PORT)"; old_port="${old_port:-8000}"
  printf "%b" "$(t p_new_port): "; read -r port
  case "$port" in ''|*[!0-9]*) err "$(t bad_port)"; return 1;; esac
  [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || { err "$(t bad_port)"; return 1; }
  set_env_var UVICORN_PORT "$port" || return 1
  ok "UVICORN_PORT=${port}"

  # Keep nginx in sync when it proxies to the local uvicorn port.
  local nginx_updated=0
  if command -v nginx >/dev/null 2>&1; then
    local f
    for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*; do
      [ -f "$f" ] || continue
      if grep -qE "proxy_pass[[:space:]]+http://127\\.0\\.0\\.1:${old_port}" "$f" 2>/dev/null; then
        sed -i "s|proxy_pass http://127.0.0.1:${old_port}|proxy_pass http://127.0.0.1:${port}|g" "$f" \
          && nginx_updated=1
      fi
    done
    if [ "$nginx_updated" -eq 1 ]; then
      if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx 2>/dev/null || true
        ok "$(t port_nginx_updated)"
      else
        warn "$(t port_nginx_manual)"
      fi
    elif systemctl is-active nginx >/dev/null 2>&1; then
      warn "$(t port_nginx_manual)"
    fi
  fi

  warn "$(t port_warn)"
  warn "$(t restart_needed)"
  if [ "$DEPLOY_MODE" = "docker" ]; then dc up -d --force-recreate "$SERVICE"; else systemctl restart "$SERVICE"; fi
}

action_view_settings() {
  local user path port pub ver
  user="$(get_runtime_var SUDO_USERNAME)"; [ -z "$user" ] && user="$(get_env_var SUDO_USERNAME)"
  path="$(get_env_var DASHBOARD_PATH)"; path="${path:-/dashboard/}"
  port="$(get_env_var UVICORN_PORT)"; port="${port:-8000}"
  pub="$(get_env_var PANEL_PUBLIC_ADDRESS)"
  ver="$(panel_version)"
  clear 2>/dev/null || true
  nx_banner
  nx_section "$(t m_view_settings)"
  nx_kv "$(t f_version)" "$ver"
  nx_kv "$(t p_admin_user)" "${user:-?}"
  nx_kv "Port" "$port"
  nx_kv "Dashboard path" "$path"
  [ -n "$pub" ] && nx_kv "Public address" "$pub"
  [ -n "$pub" ] && nx_kv "Dashboard URL" "${pub%/}${path}"
  print_footer
}

action_ssl() {
  require_root || return 1
  if command -v nexuspanel >/dev/null 2>&1; then msg "$(t ssl_delegate)"; nexuspanel https; return $?; fi
  if [ -f "$APP_DIR/scripts/setup_https.sh" ]; then msg "$(t ssl_delegate)"; bash "$APP_DIR/scripts/setup_https.sh"; else err "$(t ssl_missing)"; fi
}

action_firewall() {
  require_root || return 1
  if ! command -v ufw >/dev/null 2>&1; then
    err "$(t fw_missing)"
    if command -v apt-get >/dev/null 2>&1 && confirm "$(t fw_install_ask)"; then
      apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq ufw >/dev/null 2>&1 || {
        err "$(t fw_missing)"; return 1
      }
      ok "$(t done)"
    else
      return 1
    fi
  fi
  while true; do
    clear 2>/dev/null || true
    nx_banner
    nx_section "$(t fw_title)"
    nx_opt "1" "$(t fw_1)"
    nx_opt "2" "$(t fw_2)"
    nx_opt "3" "$(t fw_3)"
    nx_opt "4" "$(t fw_4)"
    nx_opt_exit "0" "$(t fw_back)"
    printf "\n  %b›%b %b%s%b %b›%b " "$C_BRAND" "$C_RESET" "$C_WHITE" "$(t select)" "$C_RESET" "$C_BRAND" "$C_RESET"
    read -r c || return 0
    case "$c" in
      1) printf "\n"; ufw status verbose; pause ;;
      2) printf "%b" "$(t fw_port): "; read -r p; [ -n "$p" ] && ufw allow "$p" && ok "$(t done)"; pause ;;
      3) printf "%b" "$(t fw_port): "; read -r p; [ -n "$p" ] && ufw delete allow "$p" && ok "$(t done)"; pause ;;
      4) ufw enable; pause ;;
      0) break ;;
      *) err "$(t invalid): $c"; pause ;;
    esac
  done
}

action_bbr() {
  require_root || return 1
  modprobe tcp_bbr 2>/dev/null || true
  sysctl -w net.core.default_qdisc=fq >/dev/null 2>&1 || true
  sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1 || true
  local f=/etc/sysctl.d/99-nexus-bbr.conf
  {
    echo "net.core.default_qdisc=fq"
    echo "net.ipv4.tcp_congestion_control=bbr"
  } > "$f" 2>/dev/null || true
  sysctl --system >/dev/null 2>&1 || true
  ok "$(t bbr_done)"
  sysctl net.ipv4.tcp_congestion_control 2>/dev/null || true
}

action_geo() {
  require_root || return 1
  msg "$(t geo_updating)"
  local tmp; tmp="$(mktemp -d /tmp/nexus-geo.XXXXXX)" || { err "$(t geo_fail)"; return 1; }
  # Prefer host curl (panel container often has no curl/wget).
  if ! curl -fsSL -o "$tmp/geoip.dat" "$GEOIP_URL" || ! curl -fsSL -o "$tmp/geosite.dat" "$GEOSITE_URL"; then
    rm -rf "$tmp"
    err "$(t geo_fail)"
    return 1
  fi
  if [ "$DEPLOY_MODE" = "docker" ]; then
    msg "$(t geo_via_host)"
    if dc exec -T -u 0 "$SERVICE" sh -c 'mkdir -p /usr/local/share/xray' \
      && dc cp "$tmp/geoip.dat" "${SERVICE}:/usr/local/share/xray/geoip.dat" \
      && dc cp "$tmp/geosite.dat" "${SERVICE}:/usr/local/share/xray/geosite.dat"; then
      rm -rf "$tmp"
      ok "$(t geo_done)"; action_restart_xray
    else
      rm -rf "$tmp"
      err "$(t geo_fail)"
    fi
  else
    local dir="${XRAY_ASSETS:-/usr/local/share/xray}"
    mkdir -p "$dir"
    if mv "$tmp/geoip.dat" "$dir/geoip.dat" && mv "$tmp/geosite.dat" "$dir/geosite.dat"; then
      rm -rf "$tmp"
      ok "$(t geo_done)"; action_restart_xray
    else
      rm -rf "$tmp"
      err "$(t geo_fail)"
    fi
  fi
}

action_speedtest() {
  msg "$(t speedtest_run)"
  if command -v speedtest >/dev/null 2>&1; then speedtest; return; fi
  if command -v speedtest-cli >/dev/null 2>&1; then speedtest-cli; return; fi
  if command -v python3 >/dev/null 2>&1 && python3 -c "import speedtest" >/dev/null 2>&1; then python3 -m speedtest; return; fi
  # Best-effort install (Debian/Ubuntu).
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq speedtest-cli >/dev/null 2>&1 && { speedtest-cli; return; }
  fi
  err "$(t speedtest_missing)"
}

action_create_admin() { require_root || return 1; panel_cli_tty admin create; }
action_list_admins()  { panel_cli admin list; }

action_uninstall() {
  require_root || return 1
  hr; err "$(t uninstall_warn)"; warn "$(t uninstall_keep)"; hr
  confirm "$(t m_uninstall)?" || { warn "$(t aborted)"; return 0; }
  if [ "$DEPLOY_MODE" = "docker" ]; then dc down --remove-orphans && ok "$(t done)"
  elif [ "$DEPLOY_MODE" = "systemd" ]; then
    systemctl stop "$SERVICE" 2>/dev/null || true
    systemctl disable "$SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE}.service"; systemctl daemon-reload; ok "$(t done)"
  fi
  if confirm "$(t uninstall_data)"; then
    if confirm "$(t uninstall_sure)"; then rm -rf "$DATA_DIR"; ok "$(t done)"; fi
  fi
  if confirm "$(t uninstall_bin)"; then rm -f /usr/local/bin/nexus /usr/bin/nexus 2>/dev/null || true; ok "$(t done)"; fi
  exit 0
}

action_language() {
  clear 2>/dev/null || true
  nx_banner
  nx_section "$(t ask_lang)"
  nx_opt "1" "English"
  nx_opt "2" "فارسی"
  nx_opt_exit "0" "$(t fw_back)"
  printf "\n  %b›%b %b%s%b %b›%b " "$C_BRAND" "$C_RESET" "$C_WHITE" "$(t select)" "$C_RESET" "$C_BRAND" "$C_RESET"
  read -r c || return 0
  case "$c" in
    1) save_lang en; ok "$(t lang_saved)" ;;
    2) save_lang fa; ok "$(t lang_saved)" ;;
    0) return 0 ;;
    *) err "$(t invalid): $c" ;;
  esac
}

# --------------------------------------------------------------------------
# Menu — NexusPanel brand identity (teal hub, node sections, left rail)
# --------------------------------------------------------------------------
print_footer() {
  local panel auto xray
  panel="$(state_panel)"
  auto="$(state_autostart)"
  xray="$(state_xray)"
  printf "\n"
  printf "%b  · · · · · · · · · · · · · · · · · · · · · · · ·%b\n" "$C_MUTED" "$C_RESET"
  printf "  %b◆%b %b%s%b\n" "$C_BRAND" "$C_RESET" "$C_MUTED" "$(t hub)" "$C_RESET"
  printf "  %b│%b  %-12s %b\n" "$C_BRAND_DIM" "$C_RESET" "$(t f_panel)" "$(colorized_state "$panel")"
  printf "  %b│%b  %-12s %b\n" "$C_BRAND_DIM" "$C_RESET" "$(t f_xray)" "$(colorized_state "$xray")"
  printf "  %b│%b  %-12s %b\n" "$C_BRAND_DIM" "$C_RESET" "$(t f_autostart)" "$(colorized_bool "$auto")"
}

menu() {
  clear 2>/dev/null || true
  nx_banner

  nx_section "$(t subtitle)"
  nx_opt_exit "0" "$(t m_exit)"

  nx_section "$(t grp_install)"
  nx_opt "1"  "$(t m_install)"
  nx_opt "2"  "$(t m_update)"
  nx_opt "3"  "$(t m_update_menu)"
  nx_opt "4"  "$(t m_uninstall)"

  nx_section "$(t grp_config)"
  nx_opt "5"  "$(t m_reset_userpass)"
  nx_opt "6"  "$(t m_reset_path)"
  nx_opt "7"  "$(t m_change_port)"
  nx_opt "8"  "$(t m_view_settings)"

  nx_section "$(t grp_service)"
  nx_opt "9"  "$(t m_start)"
  nx_opt "10" "$(t m_stop)"
  nx_opt "11" "$(t m_restart)"
  nx_opt "12" "$(t m_restart_xray)"
  nx_opt "13" "$(t m_status)"
  nx_opt "14" "$(t m_logs)"

  nx_section "$(t grp_autostart)"
  nx_opt "15" "$(t m_enable_auto)"
  nx_opt "16" "$(t m_disable_auto)"

  nx_section "$(t grp_network)"
  nx_opt "17" "$(t m_ssl)"
  nx_opt "18" "$(t m_firewall)"
  nx_opt "19" "$(t m_bbr)"
  nx_opt "20" "$(t m_geo)"
  nx_opt "21" "$(t m_speedtest)"

  nx_section "$(t grp_admin)"
  nx_opt "22" "$(t m_create_admin)"
  nx_opt "23" "$(t m_list_admins)"

  nx_section "$(t grp_lang)"
  nx_opt "L"  "$(t m_lang)"

  print_footer
  nx_prompt
}

run_choice() {
  case "$1" in
    1) action_install ;;
    2) action_update ;;
    3) action_update_menu ;;
    4) action_uninstall ;;
    5) action_reset_userpass ;;
    6) action_reset_path ;;
    7) action_change_port ;;
    8) action_view_settings ;;
    9) action_start ;;
    10) action_stop ;;
    11) action_restart ;;
    12) action_restart_xray ;;
    13) action_status ;;
    14) action_logs ;;
    15) action_enable_auto ;;
    16) action_disable_auto ;;
    17) action_ssl ;;
    18) action_firewall ;;
    19) action_bbr ;;
    20) action_geo ;;
    21) action_speedtest ;;
    22) action_create_admin ;;
    23) action_list_admins ;;
    l|L) action_language ;;
    0|q|Q) exit 0 ;;
    *) err "$(t invalid): $1" ;;
  esac
}

usage() {
  cat <<EOF
nexus — NexusPanel host management console

Usage:
  nexus                 Open the interactive menu (bilingual EN/FA)
  nexus status | start | stop | restart | restart-xray
  nexus logs            Follow panel logs
  nexus update          Pull latest + rebuild + restart
  nexus password        Reset an admin username/password
  nexus settings        View current settings
  nexus ssl             Set up / refresh HTTPS
  nexus firewall        Manage UFW
  nexus bbr             Enable BBR
  nexus geo             Update Xray geo files
  nexus create-admin | admins
  nexus lang <en|fa>    Set menu language
  nexus uninstall
  nexus help
EOF
}

main() {
  if [ ! -d "$APP_DIR" ]; then err "$(t not_installed): $APP_DIR"; exit 1; fi
  load_lang
  detect_deploy_mode

  if [ "$#" -gt 0 ]; then
    case "$1" in
      status)        action_status ;;
      start)         action_start ;;
      stop)          action_stop ;;
      restart)       action_restart ;;
      restart-xray)  action_restart_xray ;;
      logs)          action_logs ;;
      update)        action_update ;;
      password|passwd) action_reset_userpass ;;
      settings)      action_view_settings ;;
      ssl|https)     action_ssl ;;
      firewall)      action_firewall ;;
      bbr)           action_bbr ;;
      geo)           action_geo ;;
      create-admin)  action_create_admin ;;
      admins)        action_list_admins ;;
      lang)          [ -n "${2:-}" ] && { save_lang "$2"; ok "$(t lang_saved)"; } || printf '%s\n' "$NEXUS_LANG" ;;
      uninstall)     action_uninstall ;;
      help|-h|--help) usage ;;
      *) err "Unknown command: $1"; usage; exit 1 ;;
    esac
    exit $?
  fi

  while true; do
    menu
    read -r choice || exit 0
    printf "\n"
    run_choice "$choice"
    printf "\n"
    pause
  done
}

main "$@"
