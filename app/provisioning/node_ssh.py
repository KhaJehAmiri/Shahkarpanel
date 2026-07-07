"""Resolve SSH credentials for panel → node maintenance (rebuild, TLS, diagnostics).

Secrets live under ``/var/lib/nexuspanel/secrets/`` (outside the git checkout)
so they are not exposed via the ``.:/code`` bind mount inside the panel
container. Override with ``NODE_SSH_KEY_FILE`` / ``WG_NODE_SSH_PASSWORD_FILE``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DEFAULT_SECRETS_DIR = Path(
    os.environ.get("NEXUSPANEL_SECRETS_DIR", "/var/lib/nexuspanel/secrets")
)
DEFAULT_KEY_FILE = DEFAULT_SECRETS_DIR / "nexuspanel_node"
DEFAULT_PASSWORD_FILE = DEFAULT_SECRETS_DIR / "wg_node_ssh"


def key_file_path() -> Path:
    return Path(os.environ.get("NODE_SSH_KEY_FILE", str(DEFAULT_KEY_FILE)))


def password_file_path() -> Path:
    return Path(os.environ.get("WG_NODE_SSH_PASSWORD_FILE", str(DEFAULT_PASSWORD_FILE)))


def resolve_node_ssh(
    host: str,
    *,
    port: int = 22,
    username: str = "root",
):
    """Build :class:`SSHCredentials` for ``host`` using key or password file."""
    from app.provisioning import SSHCredentials

    key_path = key_file_path()
    if key_path.is_file():
        return SSHCredentials(
            host=host,
            port=port,
            username=username,
            private_key=key_path.read_text(),
        )
    pwd_path = password_file_path()
    if pwd_path.is_file():
        password = pwd_path.read_text().strip()
        if password:
            return SSHCredentials(
                host=host,
                port=port,
                username=username,
                password=password,
            )
    env_pwd = os.environ.get("WG_NODE_SSH_PASSWORD", "").strip()
    if env_pwd:
        return SSHCredentials(host=host, port=port, username=username, password=env_pwd)
    raise FileNotFoundError(
        f"No SSH key ({key_path}) or password file ({pwd_path}) for node access"
    )


def has_node_ssh_access() -> bool:
    try:
        resolve_node_ssh("127.0.0.1")
        return True
    except FileNotFoundError:
        return False
