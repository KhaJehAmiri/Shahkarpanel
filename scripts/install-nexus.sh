#!/usr/bin/env bash
# Install the `nexus` host management command (x-ui style).
#
# Points /usr/local/bin/nexus at scripts/nexus.sh in the panel checkout so the
# command always tracks the installed code (updates via `git pull` are picked
# up automatically). Re-runnable.
set -euo pipefail

APP_DIR="${NEXUS_APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SRC="$APP_DIR/scripts/nexus.sh"
BIN="/usr/local/bin/nexus"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

if [ ! -f "$SRC" ]; then
  echo "ERROR: $SRC not found." >&2
  exit 1
fi

chmod +x "$SRC"

# Prefer a wrapper (so NEXUS_APP_DIR is baked in) over a bare symlink.
cat > "$BIN" <<EOF
#!/usr/bin/env bash
export NEXUS_APP_DIR="${APP_DIR}"
exec "${SRC}" "\$@"
EOF
chmod +x "$BIN"

echo "Installed: $BIN -> $SRC (APP_DIR=$APP_DIR)"
echo "Run it with: nexus"
