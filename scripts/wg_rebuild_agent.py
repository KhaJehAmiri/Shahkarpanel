#!/usr/bin/env python3
"""Rebuild node-agent on a host via SSH (no full re-provision)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import provisioning
from app.provisioning.node_ssh import resolve_node_ssh
from app.xray.operations import get_tls
from config import NODE_AGENT_IMAGE, NODE_BOOTSTRAP_TOKEN, NODE_CONTROL_SECRET


def main():
    host = os.environ.get("WG_NODE_HOST", "")
    if not host:
        from app.db import GetDB, crud
        with GetDB() as db:
            node = crud.get_node_by_id(db, int(os.environ.get("WG_SMOKE_NODE_ID", "1")))
            host = node.address if node else ""
    if not host:
        print("Set WG_NODE_HOST or ensure node id=1 exists in DB", file=sys.stderr)
        sys.exit(2)
    try:
        creds = resolve_node_ssh(host)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        print("Run: python3 scripts/setup_node_ssh_access.py", file=sys.stderr)
        sys.exit(2)

    panel_url = provisioning.resolve_panel_public_url()
    try:
        client_cert_pem = get_tls()["certificate"]
    except Exception:
        client_cert_pem = None
    cmd = provisioning.build_install_command(
        panel_url,
        NODE_BOOTSTRAP_TOKEN,
        "wireguard1",
        core_kind="wireguard",
        image=NODE_AGENT_IMAGE,
        control_secret=NODE_CONTROL_SECRET or None,
        force_image_rebuild=True,
        client_cert_pem=client_cert_pem,
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
    creds = resolve_node_ssh(host)
    out = provisioning.run_remote_command(creds, refresh, exec_timeout=1800)
    print(out[-500:] if out else "done")


if __name__ == "__main__":
    main()
