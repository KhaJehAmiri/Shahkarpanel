#!/usr/bin/env bash
# Install the `shahkar` host management command.
set -euo pipefail
APP_DIR="${SHAHKAR_APP_DIR:-/opt/shahkar}"
SRC="$APP_DIR/scripts/shahkar-manager.sh"
BIN="/usr/local/bin/shahkar"
if [ ! -f "$SRC" ]; then
  echo "Missing $SRC" >&2
  exit 1
fi
cat > "$BIN" <<WRAP
#!/usr/bin/env bash
export SHAHKAR_APP_DIR="$APP_DIR"
export COMPOSE_PROJECT_NAME="\${COMPOSE_PROJECT_NAME:-shahkar}"
exec bash "$SRC" "\$@"
WRAP
chmod +x "$BIN"
echo "Installed: shahkar"
echo "Run it with: shahkar"
