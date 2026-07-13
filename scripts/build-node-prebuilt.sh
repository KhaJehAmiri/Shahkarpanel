#!/usr/bin/env bash
# Build AmneziaWG userspace binaries for bundling in SSH provision agent-bundle.
set -euo pipefail
ARCH="${1:-amd64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/node/prebuilt/linux-${ARCH}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$OUT"
case "$ARCH" in
  amd64) GOARCH=amd64 ;;
  arm64) GOARCH=arm64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

git clone --depth 1 https://github.com/amnezia-vpn/amneziawg-go.git "$TMP/amneziawg-go"
(
  cd "$TMP/amneziawg-go"
  CGO_ENABLED=0 GOARCH="$GOARCH" go build -trimpath -ldflags "-s -w" -o "$OUT/amneziawg-go" .
)

ZIP_URL="https://github.com/amnezia-vpn/amneziawg-tools/releases/download/v1.0.20260618-2/ubuntu-22.04-amneziawg-tools.zip"
curl -fsSL -o "$TMP/awgtools.zip" "$ZIP_URL"
unzip -o "$TMP/awgtools.zip" -d "$TMP/awgtools"
install -m 0755 "$TMP/awgtools/ubuntu-22.04-amneziawg-tools/awg" "$OUT/awg"
echo "Wrote $OUT/amneziawg-go and $OUT/awg"
