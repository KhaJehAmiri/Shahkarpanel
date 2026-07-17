#!/usr/bin/env bash
# Ensure host nginx shows the NexusPanel "starting" page when the panel
# upstream (:UVICORN_PORT) is down — instead of the stock nginx 502 HTML.
#
# Must run as root (writes /etc/nginx + reload). Safe to re-run.
#
# Typical callers:
#   - host CLI:  nexuspanel update / https  (root on host)
#   - panel:     update_jobs sidecar (docker run --privileged --pid=host + mounts)
#   - entrypoint: after recreate, when /usr/sbin/nginx is bind-mounted
set -euo pipefail

PANEL_PORT="${PANEL_PORT:-${UVICORN_PORT:-8000}}"
HTML_DIR="${NEXUSPANEL_NGINX_HTML:-/var/lib/nexuspanel/nginx/html}"
HTML_FILE="${HTML_DIR}/restarting.html"
SNIPPET_MARKER="@panel_restarting"
LOG="${NEXUSPANEL_ENSURE_NGINX_LOG:-/var/lib/nexuspanel/ensure-nginx-restarting.log}"

resolve_nginx() {
  local c
  for c in nginx /usr/sbin/nginx /usr/bin/nginx; do
    if [ -x "$c" ]; then
      echo "$c"
      return 0
    fi
    if command -v "$c" >/dev/null 2>&1; then
      command -v "$c"
      return 0
    fi
  done
  return 1
}

NGINX_BIN="$(resolve_nginx || true)"

log() {
  local line="[restarting-page] $*"
  echo "$line"
  mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $line" >>"$LOG" 2>/dev/null || true
}

write_html() {
  mkdir -p "$HTML_DIR"
  cat > "$HTML_FILE" <<'HTML'
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="2" />
  <meta name="robots" content="noindex" />
  <title>NexusPanel — در حال راه‌اندازی</title>
  <style>
    :root { --bg:#0f1419; --card:#1a222c; --text:#e8eef4; --muted:#8b9aab; --accent:#3d9cf0; }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; display: grid; place-items: center;
      font-family: "Vazirmatn", "Segoe UI", Tahoma, sans-serif;
      background:
        radial-gradient(ellipse at 20% 0%, rgba(61, 156, 240, 0.18), transparent 50%),
        radial-gradient(ellipse at 80% 100%, rgba(61, 156, 240, 0.08), transparent 45%),
        var(--bg);
      color: var(--text); padding: 24px;
    }
    .card {
      width: min(420px, 100%); background: var(--card);
      border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 16px;
      padding: 36px 28px 28px; text-align: center;
      box-shadow: 0 24px 48px rgba(0, 0, 0, 0.35);
    }
    .brand { font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--accent); margin-bottom: 18px; font-weight: 600; }
    h1 { font-size: 1.35rem; font-weight: 700; margin: 0 0 10px; line-height: 1.4; }
    p { margin: 0; color: var(--muted); font-size: 0.95rem; line-height: 1.6; }
    .spinner {
      width: 40px; height: 40px; margin: 22px auto 8px;
      border: 3px solid rgba(61, 156, 240, 0.2); border-top-color: var(--accent);
      border-radius: 50%; animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .en {
      margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255, 255, 255, 0.06);
      font-size: 0.82rem; color: var(--muted); direction: ltr;
      font-family: "Segoe UI", system-ui, sans-serif;
    }
  </style>
</head>
<body>
  <div class="card" role="status" aria-live="polite">
    <div class="brand">NexusPanel</div>
    <h1>پنل در حال راه‌اندازی است</h1>
    <p>پس از به‌روزرسانی یا ریستارت، چند لحظه صبر کنید. این صفحه به‌صورت خودکار باز می‌شود.</p>
    <div class="spinner" aria-hidden="true"></div>
    <p class="en">Panel is starting up — this page refreshes automatically.</p>
  </div>
  <script>setTimeout(function () { location.reload(); }, 2000);</script>
</body>
</html>
HTML
  chmod -R a+rX /var/lib/nexuspanel/nginx 2>/dev/null || true
  log "wrote ${HTML_FILE}"
}

# Insert error_page + named location into every server{} that proxies to the panel.
patch_file() {
  local file="$1"
  [ -f "$file" ] || return 0
  if ! grep -qE "proxy_pass[[:space:]]+http://127\.0\.0\.1:${PANEL_PORT}(/|;|[[:space:]])" "$file"; then
    return 0
  fi
  if grep -q "$SNIPPET_MARKER" "$file"; then
    if ! grep -q "proxy_connect_timeout" "$file"; then
      # shellcheck disable=SC2016
      sed -i "/proxy_pass http:\\/\\/127.0.0.1:${PANEL_PORT}/a\\        proxy_connect_timeout 1s;" "$file" || true
      log "added proxy_connect_timeout in ${file}"
    fi
    return 0
  fi

  python3 - "$file" "$PANEL_PORT" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
port = sys.argv[2]
text = path.read_text()
if "@panel_restarting" in text:
    sys.exit(0)

needle_re = re.compile(
    rf"(^[ \t]*proxy_pass[ \t]+http://127\.0\.0\.1:{re.escape(port)}\b[^;]*;)",
    re.M,
)
m = needle_re.search(text)
if not m:
    sys.exit(0)

block = f"""    error_page 502 503 504 = @panel_restarting;

    location @panel_restarting {{
        default_type text/html;
        charset utf-8;
        add_header Cache-Control "no-store" always;
        add_header Retry-After "2" always;
        root /var/lib/nexuspanel/nginx/html;
        rewrite ^ /restarting.html break;
    }}

"""
idx = m.start()
loc = text.rfind("\n    location ", 0, idx)
insert_at = loc + 1 if loc != -1 else text.rfind("\n", 0, idx) + 1

chunk_end = text.find("\n    }", idx)
chunk = text[idx:chunk_end] if chunk_end != -1 else text[idx:]
extra = ""
if "proxy_connect_timeout" not in chunk:
    extra = "\n        proxy_connect_timeout 1s;"

new = text[:insert_at] + block + text[insert_at:]
if extra:
    new = needle_re.sub(r"\1" + extra, new, count=1)
path.write_text(new)
print(f"patched {path}")
PY
}

reload_nginx() {
  if [ -n "$NGINX_BIN" ]; then
    if ! "$NGINX_BIN" -t >/dev/null 2>&1; then
      log "WARNING: nginx -t failed after patch — not reloading"
      "$NGINX_BIN" -t 2>&1 | tee -a "$LOG" | tail -20 || true
      return 1
    fi
    if systemctl reload nginx 2>/dev/null; then
      log "nginx reloaded (systemctl)"
      return 0
    fi
    if "$NGINX_BIN" -s reload 2>/dev/null; then
      log "nginx reloaded (nginx -s reload)"
      return 0
    fi
  fi
  if [ -f /run/nginx.pid ]; then
    local pid
    pid="$(tr -d ' \n' </run/nginx.pid || true)"
    if [ -n "${pid:-}" ] && kill -HUP "$pid" 2>/dev/null; then
      log "nginx reloaded (HUP pid=${pid})"
      return 0
    fi
  fi
  log "WARNING: could not reload nginx (config may still be patched for next reload)"
  return 1
}

main() {
  if [ "$(id -u)" -ne 0 ]; then
    log "ERROR: must run as root (got uid=$(id -u)) — refusing to patch nginx"
    exit 1
  fi

  if [ ! -d /etc/nginx/sites-enabled ] && [ ! -d /etc/nginx/sites-available ]; then
    log "/etc/nginx sites dirs missing — skip (not mounted or nginx absent)"
    exit 0
  fi

  if [ -z "$NGINX_BIN" ]; then
    log "nginx binary not found in PATH — will patch configs and try HUP via /run/nginx.pid"
  else
    log "using nginx binary: ${NGINX_BIN}"
  fi

  write_html

  local -A seen=()
  local f real
  shopt -s nullglob
  for f in \
    /etc/nginx/sites-available/nexuspanel \
    /etc/nginx/sites-available/nexuspanel*.conf \
    /etc/nginx/sites-enabled/nexuspanel \
    /etc/nginx/sites-enabled/*
  do
    [ -e "$f" ] || continue
    # Skip directories / broken symlinks.
    [ -f "$f" ] || continue
    real="$(readlink -f "$f" 2>/dev/null || echo "$f")"
    [ -n "${seen[$real]:-}" ] && continue
    seen[$real]=1
    if out="$(patch_file "$real" 2>&1)"; then
      [ -n "$out" ] && log "$out"
    fi
  done
  shopt -u nullglob

  reload_nginx || true
}

main "$@"
