#!/usr/bin/env python3
"""Bootstrap persistent SSH key access from the panel host to a WG/Xray node.

1. Generates ``/var/lib/nexuspanel/secrets/nexuspanel_node`` (ed25519) if missing.
2. Installs the public key on the remote ``authorized_keys`` (password once).
3. Stores the password in ``/var/lib/nexuspanel/secrets/wg_node_ssh`` as fallback (chmod 600).

After this, maintenance scripts (``wg_rebuild_agent.py``, TLS issue, etc.) prefer
the key and no longer depend on password auth.

Usage:
  python3 scripts/setup_node_ssh_access.py
  python3 scripts/setup_node_ssh_access.py --host YOUR_NODE_IP --user root
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.provisioning import ProvisioningError, run_remote_command, ssh_available
from app.provisioning.node_ssh import (
    DEFAULT_KEY_FILE,
    DEFAULT_PASSWORD_FILE,
    key_file_path,
    resolve_node_ssh,
)


def _chmod_secret(path: Path) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _ensure_local_key(key_path: Path) -> Path:
    pub_path = Path(str(key_path) + ".pub")
    if key_path.is_file():
        return pub_path
    key_path.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    subprocess.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(key_path),
            "-N",
            "",
            "-C",
            "nexuspanel-node-access",
        ],
        check=True,
        capture_output=True,
    )
    _chmod_secret(key_path)
    _chmod_secret(pub_path)
    return pub_path


def _install_pubkey(host: str, username: str, port: int, pub_path: Path, password: str) -> None:
    from app.provisioning import SSHCredentials

    pubkey = pub_path.read_text().strip()
    marker = "nexuspanel-node-access"
    remote_cmd = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"grep -qF '{marker}' ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo {repr(pubkey)} >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys"
    )
    creds = SSHCredentials(host=host, port=port, username=username, password=password)
    run_remote_command(creds, remote_cmd, exec_timeout=60)


def _verify_key_login(host: str, username: str, port: int) -> bool:
    try:
        creds = resolve_node_ssh(host, port=port, username=username)
        run_remote_command(creds, "echo NEXUS_SSH_OK", exec_timeout=30)
        return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup panel → node SSH key access")
    parser.add_argument("--host", default=os.environ.get("WG_NODE_HOST", ""))
    parser.add_argument("--user", default="root")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument(
        "--password",
        default=os.environ.get("WG_NODE_SSH_PASSWORD", ""),
        help="SSH password (also written to wg_node_ssh in secrets dir if provided)",
    )
    args = parser.parse_args()

    if not args.host:
        from app.db import GetDB, crud
        with GetDB() as db:
            nodes = crud.get_wireguard_nodes(db)
            args.host = nodes[0].address if nodes else ""
    if not args.host:
        print("--host or WG_NODE_HOST required (or add a WG node in the panel)", file=sys.stderr)
        return 2

    if not ssh_available():
        print("paramiko not installed", file=sys.stderr)
        return 2

    key_path = key_file_path()
    pub_path = _ensure_local_key(key_path)
    print(f"local key: {key_path}")

    if _verify_key_login(args.host, args.user, args.port):
        print(f"key auth already works for {args.user}@{args.host}")
        return 0

    password = args.password.strip()
    if not password and DEFAULT_PASSWORD_FILE.is_file():
        password = DEFAULT_PASSWORD_FILE.read_text().strip()
    if not password:
        print(f"Provide --password or create {DEFAULT_PASSWORD_FILE}", file=sys.stderr)
        return 2

    if args.password:
        DEFAULT_PASSWORD_FILE.write_text(password + "\n")
        _chmod_secret(DEFAULT_PASSWORD_FILE)
        print(f"stored password fallback: {DEFAULT_PASSWORD_FILE}")

    print(f"installing pubkey on {args.user}@{args.host}...")
    try:
        _install_pubkey(args.host, args.user, args.port, pub_path, password)
    except ProvisioningError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1

    if _verify_key_login(args.host, args.user, args.port):
        print("SSH key access OK")
        return 0

    print("pubkey installed but key login verification failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
