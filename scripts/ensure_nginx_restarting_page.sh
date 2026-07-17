#!/usr/bin/env bash
# Ensure host nginx shows the NexusPanel "starting" page when the panel
# upstream (:UVICORN_PORT) is down — instead of the stock nginx 502 HTML.
#
# Safe to re-run. Patches existing vhosts that proxy to the panel port but
# were created before this feature (or by subscription helpers) without
# re-running full `nexuspanel https`.
set -euo pipefail

PANEL_PORT="${PANEL_PORT:-${UVICORN_PORT:-8000}}"
HTML_DIR="${NEXUSPANEL_NGINX_HTML:-/var/lib/nexuspanel/nginx/html}"
HTML_FILE="${HTML_DIR}/restarting.html"
SNIPPET_MARKER="@panel_restarting"

log() { echo "[restarting-page] $*"; }

write_html() {
  mkdir -p "$HTML_DIR"
  if [ ! -f "$HTML_FILE" ]; then
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
    log "wrote ${HTML_FILE}"
  fi
  chmod -R a+rX /var/lib/nexuspanel/nginx 2>/dev/null || true
}

# Insert error_page + named location into a server{} that proxies to the panel
# but does not yet have @panel_restarting.
patch_file() {
  local file="$1"
  [ -f "$file" ] || return 0
  grep -q "proxy_pass http://127.0.0.1:${PANEL_PORT}" "$file" || return 0
  if grep -q "$SNIPPET_MARKER" "$file"; then
    # Still tighten connect timeout if missing (avoid 60s blank wait).
    if ! grep -q "proxy_connect_timeout" "$file"; then
      sed -i "/proxy_pass http:\\/\\/127.0.0.1:${PANEL_PORT}/a\\        proxy_connect_timeout 1s;" "$file"
      log "added proxy_connect_timeout in ${file}"
    fi
    return 0
  fi

  python3 - "$file" "$PANEL_PORT" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
port = sys.argv[2]
text = path.read_text()
needle = f"proxy_pass http://127.0.0.1:{port};"
if "@panel_restarting" in text or needle not in text:
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
# Insert once before the first panel proxy_pass (indent-aware: at server body level).
idx = text.find(needle)
# Walk back to start of the line containing proxy_pass's location block —
# insert immediately before that `location` if present, else before proxy_pass line.
loc = text.rfind("\n    location ", 0, idx)
insert_at = loc + 1 if loc != -1 else text.rfind("\n", 0, idx) + 1
# Ensure connect timeout on the proxy location.
chunk_end = text.find("\n    }", idx)
chunk = text[idx:chunk_end] if chunk_end != -1 else text[idx:]
extra = ""
if "proxy_connect_timeout" not in chunk:
    extra = "\n        proxy_connect_timeout 1s;"
new = text[:insert_at] + block + text[insert_at:]
if extra:
    new = new.replace(needle, needle + extra, 1)
path.write_text(new)
print(f"patched {path}")
PY
}

main() {
  if ! command -v nginx >/dev/null 2>&1; then
    log "nginx not installed — skip"
    exit 0
  fi
  write_html

  local -A seen=()
  local f real
  shopt -s nullglob
  for f in \
    /etc/nginx/sites-available/nexuspanel \
    /etc/nginx/sites-available/nexuspanel-sub-*.conf \
    /etc/nginx/sites-enabled/nexuspanel \
    /etc/nginx/sites-enabled/nexuspanel-sub-*.conf
  do
    [ -e "$f" ] || continue
    real="$(readlink -f "$f" 2>/dev/null || echo "$f")"
    [ -n "${seen[$real]:-}" ] && continue
    seen[$real]=1
    patch_file "$real"
  done
  shopt -u nullglob

  if nginx -t >/dev/null 2>&1; then
    if systemctl reload nginx 2>/dev/null \
      || nginx -s reload 2>/dev/null \
      || { [ -f /run/nginx.pid ] && kill -HUP "$(cat /run/nginx.pid)"; }; then
      log "nginx reloaded"
    else
      log "nginx config ok (reload skipped)"
    fi
  else
    log "WARNING: nginx -t failed after patch — not reloading (run nginx -t)"
    nginx -t 2>&1 | tail -20 || true
    exit 1
  fi
}

main "$@"
