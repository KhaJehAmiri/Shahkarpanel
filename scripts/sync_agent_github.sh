#!/usr/bin/env bash
# Upload the node-agent docker-save tarball to the GitHub Release tag used by
# NODE_AGENT_PACKAGE_URL (default: tag ``node-agent``).
#
# Usage:
#   bash scripts/sync_agent_github.sh
#   NODE_AGENT_GITHUB_REPO=KhaJehAmiri/nexuspanel \
#   NODE_AGENT_GITHUB_TAG=node-agent \
#   bash scripts/sync_agent_github.sh
#
# Requires ``gh`` authenticated with permission to upload release assets.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/nexuspanel}"
CACHE_DIR="${CACHE_DIR:-/var/lib/nexuspanel/cache/agent-images}"
IMAGE="${NODE_AGENT_IMAGE:-nexuspanel/node:latest}"
ASSET_NAME="${NODE_AGENT_GITHUB_ASSET:-nexuspanel-node-agent-image.tar.gz}"
TAG="${NODE_AGENT_GITHUB_TAG:-node-agent}"
REPO="${NODE_AGENT_GITHUB_REPO:-}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh not installed — skip GitHub package upload."
  exit 0
fi

if [ -z "$REPO" ]; then
  if command -v git >/dev/null 2>&1 && [ -d "${APP_DIR}/.git" ]; then
    REPO="$(git -C "${APP_DIR}" remote get-url origin 2>/dev/null | sed -E 's#(git@github\.com:|https://github\.com/)##;s#\.git$##' || true)"
  fi
fi
if [ -z "$REPO" ]; then
  REPO="KhaJehAmiri/nexuspanel"
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh not authenticated — skip GitHub package upload."
  exit 0
fi

SRC="$(ls -t "${CACHE_DIR}"/*.tar.gz 2>/dev/null | head -1 || true)"
if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
  echo "No agent-image tarball in ${CACHE_DIR}; building via docker save..."
  mkdir -p "${CACHE_DIR}"
  SRC="${CACHE_DIR}/manual-sync.tar.gz"
  docker save "${IMAGE}" | gzip -c > "${SRC}"
fi

STAGED="${CACHE_DIR}/${ASSET_NAME}"
if [ "$(basename "$SRC")" != "$ASSET_NAME" ]; then
  cp -f "$SRC" "$STAGED"
  SRC="$STAGED"
fi

echo "Uploading $(du -h "$SRC" | awk '{print $1}') → github.com/${REPO}/releases/tag/${TAG} (${ASSET_NAME})"

if ! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  gh release create "$TAG" --repo "$REPO" \
    --title "Node agent image" \
    --notes "Prebuilt nexuspanel/node docker-save tarball for SSH provision."
fi

gh release upload "$TAG" "$SRC" --repo "$REPO" --clobber

echo "GitHub package OK: https://github.com/${REPO}/releases/download/${TAG}/${ASSET_NAME}"
