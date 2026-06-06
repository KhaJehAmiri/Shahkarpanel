#!/usr/bin/env python3
"""Rebuild node-agent on a host via SSH (no full re-provision)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import provisioning
from config import NODE_AGENT_IMAGE, NODE_BOOTSTRAP_TOKEN, NODE_CONTROL_SECRET


def main():
    host = os.environ.get("WG_NODE_HOST", "178.83.45.253")
    password = os.environ.get("WG_NODE_SSH_PASSWORD", "")
    if not password:
        path = os.environ.get("WG_NODE_SSH_PASSWORD_FILE", "/opt/nexuspanel/.wg_node_ssh")
        if os.path.isfile(path):
            password = open(path).read().strip()
    if not password:
        print("Set WG_NODE_SSH_PASSWORD or create /opt/nexuspanel/.wg_node_ssh", file=sys.stderr)
        sys.exit(2)

    panel_url = provisioning.resolve_panel_public_url()
    cmd = provisioning.build_install_command(
        panel_url,
        NODE_BOOTSTRAP_TOKEN,
        "wireguard1",
        core_kind="wireguard",
        image=NODE_AGENT_IMAGE,
        control_secret=NODE_CONTROL_SECRET or None,
        force_image_rebuild=True,
    )
    # Host already has agent — only rebuild image + restart container + bootstrap.
    refresh = (
        "set -e; "
        + cmd.split("docker rm -f nexusnode", 1)[0]
        + cmd[cmd.index("docker rm -f nexusnode"):]
    )
    # Bootstrap returns 409 when the node is already registered — ignore that.
    if "curl -fsSL" in refresh:
        head, tail = refresh.rsplit("curl -fsSL", 1)
        refresh = head + "(curl -fsSL" + tail + ") || true"
    creds = provisioning.SSHCredentials(host=host, password=password)
    out = provisioning.run_remote_command(creds, refresh, exec_timeout=1800)
    print(out[-500:] if out else "done")


if __name__ == "__main__":
    main()
