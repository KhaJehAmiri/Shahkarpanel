"""Resolve SSH credentials for panel → node maintenance (rebuild, TLS, diagnostics).

Secrets live under ``/var/lib/shahkar/secrets/`` (outside the git checkout)
so they are not exposed via the ``.:/code`` bind mount inside the panel
container. Override with ``NODE_SSH_KEY_FILE`` / ``WG_NODE_SSH_PASSWORD_FILE``.

Pre-rebrand installs may still keep secrets under ``/var/lib/nexuspanel/secrets``
(and an older key filename); those paths are checked as a fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

DEFAULT_SECRETS_DIR = Path(
    os.environ.get("SHAHKAR_SECRETS_DIR", "/var/lib/shahkar/secrets")
)
DEFAULT_KEY_FILE = DEFAULT_SECRETS_DIR / "shahkar_node"
DEFAULT_PASSWORD_FILE = DEFAULT_SECRETS_DIR / "wg_node_ssh"

_LEGACY_KEY_NAMES = ("shahkar_node", "nexuspanel_node", "nexus_node")

#: Port every caller assumes when it has no better information.
DEFAULT_SSH_PORT = 22
#: Ports worth trying when the remembered one does not answer.
SSH_PORT_FALLBACKS = (22, 2222)


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


def ssh_port_cache_path() -> Path:
    """Where the per-host SSH port map lives (new data dir, else pre-rebrand)."""
    for directory in _secrets_dirs():
        path = directory / "node_ssh_ports.json"
        if path.is_file():
            return path
    return DEFAULT_SECRETS_DIR / "node_ssh_ports.json"


def remembered_ssh_port(host: str) -> Optional[int]:
    """Last port known to work for ``host``, or ``None``."""
    host = (host or "").strip()
    if not host:
        return None
    path = ssh_port_cache_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get(host)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    try:
        return int(raw) or None
    except (TypeError, ValueError):
        return None


def remember_ssh_port(host: str, port: int) -> None:
    """Persist the port that just worked for ``host``."""
    host = (host or "").strip()
    if not host or not port:
        return
    path = ssh_port_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        if data.get(host) == int(port):
            return
        data[host] = int(port)
        path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


def resolve_ssh_port(host: str, preferred: Optional[int] = None) -> int:
    """Best-guess SSH port for ``host``.

    Callers overwhelmingly pass the ``22`` default without knowing the node's
    real port, so an explicit ``22`` is treated as "unset" and the remembered
    port wins. Anything else the caller asks for is honoured as-is.
    """
    if preferred and int(preferred) != DEFAULT_SSH_PORT:
        return int(preferred)
    remembered = remembered_ssh_port(host)
    if remembered:
        return remembered
    for env_key in ("NODE_SSH_PORT", "WG_NODE_SSH_PORT"):
        raw = os.environ.get(env_key, "").strip()
        if raw.isdigit() and int(raw):
            return int(raw)
    return int(preferred or DEFAULT_SSH_PORT)


def ssh_port_candidates(host: str, preferred: Optional[int] = None) -> List[int]:
    """Ports to try for ``host``: best guess first, then the usual suspects."""
    ports: List[int] = []
    for port in (resolve_ssh_port(host, preferred), *SSH_PORT_FALLBACKS):
        if port and port not in ports:
            ports.append(int(port))
    return ports


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
    resolve_port: bool = True,
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

    Pass ``resolve_port=False`` when ``port`` is already a deliberate choice
    (e.g. a caller walking :func:`ssh_port_candidates`), so the remembered
    port does not override it.
    """
    from app.provisioning import SSHCredentials

    # Most callers never learn a node's real SSH port and just pass the 22
    # default, so honour the remembered per-host port here rather than making
    # every call site remember to look it up.
    if resolve_port:
        port = resolve_ssh_port(host, port)

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
