"""Resolve SSH credentials for panel → node maintenance (rebuild, TLS, diagnostics).

Secrets live under ``/var/lib/shahkar/secrets/`` (outside the git checkout)
so they are not exposed via the ``.:/code`` bind mount inside the panel
container. Override with ``NODE_SSH_KEY_FILE`` / ``WG_NODE_SSH_PASSWORD_FILE``.

Pre-rebrand installs may still keep secrets under ``/var/lib/nexuspanel/secrets``
(and an older key filename); those paths are checked as a fallback.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

DEFAULT_SECRETS_DIR = Path(
    os.environ.get("SHAHKAR_SECRETS_DIR", "/var/lib/shahkar/secrets")
)
DEFAULT_KEY_FILE = DEFAULT_SECRETS_DIR / "shahkar_node"
DEFAULT_PASSWORD_FILE = DEFAULT_SECRETS_DIR / "wg_node_ssh"

_LEGACY_KEY_NAMES = ("shahkar_node", "nexuspanel_node", "nexus_node")


def _secrets_dirs() -> List[Path]:
    """Candidate secrets directories, newest first."""
    seen = set()
    out: List[Path] = []
    for raw in (
        os.environ.get("SHAHKAR_SECRETS_DIR", "").strip(),
        "/var/lib/shahkar/secrets",
        "/var/lib/nexuspanel/secrets",
        str(Path(os.environ.get("SHAHKAR_DATA_DIR", "/var/lib/shahkar")) / "secrets"),
        str(Path(os.environ.get("NEXUSPANEL_DATA_DIR", "/var/lib/nexuspanel")) / "secrets"),
    ):
        if not raw:
            continue
        path = Path(raw)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def key_file_path() -> Path:
    override = os.environ.get("NODE_SSH_KEY_FILE", "").strip()
    if override:
        return Path(override)
    for directory in _secrets_dirs():
        for name in _LEGACY_KEY_NAMES:
            path = directory / name
            if path.is_file():
                return path
    return DEFAULT_KEY_FILE


def password_file_path() -> Path:
    override = os.environ.get("WG_NODE_SSH_PASSWORD_FILE", "").strip()
    if override:
        return Path(override)
    for directory in _secrets_dirs():
        path = directory / "wg_node_ssh"
        if path.is_file():
            return path
    return DEFAULT_PASSWORD_FILE


def resolve_node_ssh(
    host: str,
    *,
    port: int = 22,
    username: str = "root",
):
    """Build :class:`SSHCredentials` for ``host`` using key or password file.

    Returns the *first* candidate from :func:`resolve_node_ssh_candidates` for
    callers that only ever try one credential (e.g. maintenance scripts).
    """
    candidates = resolve_node_ssh_candidates(host, port=port, username=username)
    return candidates[0]


def resolve_node_ssh_candidates(
    host: str,
    *,
    port: int = 22,
    username: str = "root",
):
    """All usable :class:`SSHCredentials` for ``host``, key first then password.

    A stored key file only proves a keypair was *generated* at some point —
    not that its public half was ever actually installed in this specific
    node's ``authorized_keys`` (e.g. a node added before the key existed, or
    added by a different flow). Returning every candidate lets callers that
    actually attempt the connection (``control_tunnel.ensure_node_tunnel``)
    fall back to the password automatically instead of getting permanently
    stuck retrying a key that will never authenticate — no manual
    ``setup_node_ssh_access.py`` run required.
    """
    from app.provisioning import SSHCredentials

    candidates = []
    key_path = key_file_path()
    if key_path.is_file():
        try:
            private_key = key_path.read_text()
        except OSError:
            private_key = ""
        if private_key:
            candidates.append(
                SSHCredentials(host=host, port=port, username=username, private_key=private_key)
            )

    password = ""
    pwd_path = password_file_path()
    if pwd_path.is_file():
        try:
            password = pwd_path.read_text().strip()
        except OSError:
            password = ""
    if not password:
        password = os.environ.get("WG_NODE_SSH_PASSWORD", "").strip()
    if password:
        candidates.append(SSHCredentials(host=host, port=port, username=username, password=password))

    if not candidates:
        raise FileNotFoundError(
            f"No SSH key ({key_path}) or password file ({pwd_path}) for node access"
        )
    return candidates


def has_node_ssh_access() -> bool:
    try:
        resolve_node_ssh("127.0.0.1")
        return True
    except FileNotFoundError:
        return False
