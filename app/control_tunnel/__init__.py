"""Panel-side SSH local-forward tunnels for node control (RPyC / gRPC).

When the direct panel→node path drops application data (common across some
Iran↔abroad routes), the panel opens ``ssh -L`` to the node's loopback ports
and dials ``127.0.0.1`` instead. Client traffic still uses ``provision_host``.
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger("uvicorn.error")

# Local bind base: control = BASE + 2*node_id, api = +1
LOCAL_PORT_BASE = int(os.environ.get("NEXUSPANEL_CONTROL_TUNNEL_BASE", "27000"))

_lock = threading.RLock()
_tunnels: Dict[int, "TunnelProc"] = {}


class TunnelError(RuntimeError):
    """Control tunnel could not be established."""


@dataclass
class TunnelProc:
    node_id: int
    host: str
    local_control: int
    local_api: int
    remote_control: int
    remote_api: int
    proc: subprocess.Popen
    key_path: Optional[str] = None
    started_at: float = field(default_factory=time.time)


def local_ports(node_id: int) -> Tuple[int, int]:
    control = LOCAL_PORT_BASE + 2 * int(node_id)
    return control, control + 1


def is_active(node_id: int) -> bool:
    with _lock:
        tun = _tunnels.get(node_id)
        if not tun:
            return False
        if tun.proc.poll() is not None:
            return False
        return _port_open(tun.local_control)


def dial_endpoints(node_id: int) -> Optional[Tuple[str, int, int]]:
    """Return ``(host, control_port, api_port)`` when a live tunnel exists."""
    with _lock:
        tun = _tunnels.get(node_id)
        if not tun or tun.proc.poll() is not None:
            return None
        if not _port_open(tun.local_control):
            return None
        return ("127.0.0.1", tun.local_control, tun.local_api)


def has_ssh_for_host(host: str) -> bool:
    host = (host or "").strip()
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return False
    try:
        from app.provisioning.node_ssh import resolve_node_ssh_candidates

        return bool(resolve_node_ssh_candidates(host))
    except Exception:
        return False


def _spawn_ssh_tunnel(
    creds,
    host: str,
    lc: int,
    la: int,
    remote_port: int,
    remote_api_port: int,
    ssh_port: int,
) -> Tuple[subprocess.Popen, Optional[str]]:
    """Start one ``ssh -L`` attempt with a single credential; raise on failure."""
    key_path = None
    env = os.environ.copy()
    cmd = [
        "ssh",
        "-N",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=20",
        "-o", "ServerAliveCountMax=3",
        "-o", "ConnectTimeout=15",
        "-p", str(creds.port or ssh_port),
        "-L", f"127.0.0.1:{lc}:127.0.0.1:{int(remote_port)}",
        "-L", f"127.0.0.1:{la}:127.0.0.1:{int(remote_api_port)}",
    ]
    if creds.private_key:
        fd, key_path = tempfile.mkstemp(prefix="np-node-ssh-", suffix=".key")
        os.close(fd)
        with open(key_path, "w") as f:
            f.write(creds.private_key if creds.private_key.endswith("\n") else creds.private_key + "\n")
        os.chmod(key_path, 0o600)
        cmd.extend(["-i", key_path, "-o", "IdentitiesOnly=yes"])
    elif creds.password:
        if not shutil.which("sshpass"):
            raise TunnelError(
                "Node SSH uses a password but sshpass is not installed; "
                "configure a panel node SSH key instead"
            )
        env["SSHPASS"] = creds.password
        cmd = ["sshpass", "-e"] + cmd
    else:
        raise TunnelError("No SSH key or password for control tunnel")

    cmd.append(f"{creds.username}@{host}")

    def _cleanup_key() -> None:
        if key_path:
            try:
                os.unlink(key_path)
            except OSError:
                pass

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        _cleanup_key()
        raise TunnelError(f"Failed to start SSH tunnel: {exc}") from exc

    # Wait until the local listen port is up (or the process dies).
    deadline = time.time() + 20.0
    while time.time() < deadline:
        if proc.poll() is not None:
            err = ""
            try:
                err = (proc.stderr.read() or b"").decode("utf-8", "replace")[:400]
            except Exception:
                pass
            _cleanup_key()
            raise TunnelError(
                f"SSH control tunnel exited early ({'key' if creds.private_key else 'password'} auth)"
                + (f": {err.strip()}" if err.strip() else "")
            )
        if _port_open(lc):
            return proc, key_path
        time.sleep(0.2)

    _kill_proc(proc)
    _cleanup_key()
    raise TunnelError(f"SSH control tunnel did not open local port {lc}")


def ensure_node_tunnel(
    node_id: int,
    host: str,
    *,
    remote_port: int = 62050,
    remote_api_port: int = 62051,
    ssh_port: int = 22,
    username: str = "root",
) -> Tuple[int, int]:
    """Ensure an SSH local-forward tunnel for ``node_id``. Returns local ports."""
    host = (host or "").strip()
    if not host:
        raise TunnelError("No SSH host for control tunnel")
    if host in ("127.0.0.1", "localhost", "::1"):
        # Already dialing loopback — nothing to tunnel.
        return remote_port, remote_api_port

    lc, la = local_ports(node_id)
    with _lock:
        existing = _tunnels.get(node_id)
        if (
            existing
            and existing.proc.poll() is None
            and existing.host == host
            and existing.local_control == lc
            and _port_open(lc)
        ):
            return lc, la
        if existing:
            _stop_locked(node_id)

        if not shutil.which("ssh"):
            raise TunnelError("ssh client not available in the panel container")

        from app.provisioning.node_ssh import resolve_node_ssh_candidates

        try:
            candidates = resolve_node_ssh_candidates(host, port=ssh_port, username=username)
        except FileNotFoundError as exc:
            raise TunnelError(str(exc)) from exc

        # A stored key file doesn't guarantee its pubkey was ever installed on
        # *this* node's authorized_keys (e.g. added before the key existed).
        # Try every configured credential (key, then password) instead of
        # failing permanently on the first one that doesn't authenticate —
        # this is what lets the control-tunnel fallback work automatically
        # without a human re-running the SSH bootstrap script per node.
        proc = None
        key_path = None
        last_err: Optional[TunnelError] = None
        for creds in candidates:
            try:
                proc, key_path = _spawn_ssh_tunnel(
                    creds, host, lc, la, remote_port, remote_api_port, ssh_port
                )
                break
            except TunnelError as exc:
                last_err = exc
                proc = None
                key_path = None
                continue
        if proc is None:
            raise last_err or TunnelError("No SSH key or password for control tunnel")

        _tunnels[node_id] = TunnelProc(
            node_id=node_id,
            host=host,
            local_control=lc,
            local_api=la,
            remote_control=int(remote_port),
            remote_api=int(remote_api_port),
            proc=proc,
            key_path=key_path,
        )
        logger.info(
            "Control tunnel up for node %s via %s → 127.0.0.1:%s/%s",
            node_id,
            host,
            lc,
            la,
        )
        return lc, la


def stop_node_tunnel(node_id: int) -> None:
    with _lock:
        _stop_locked(node_id)


def heal_tunnels() -> None:
    """Restart any tracked tunnels whose SSH process has died."""
    with _lock:
        dead = [
            nid
            for nid, tun in list(_tunnels.items())
            if tun.proc.poll() is not None or not _port_open(tun.local_control)
        ]
        snapshots = {
            nid: (
                _tunnels[nid].host,
                _tunnels[nid].remote_control,
                _tunnels[nid].remote_api,
            )
            for nid in dead
            if nid in _tunnels
        }
        for nid in dead:
            _stop_locked(nid)

    for nid, (host, rp, rap) in snapshots.items():
        try:
            ensure_node_tunnel(nid, host, remote_port=rp, remote_api_port=rap)
        except Exception as exc:
            logger.warning("Control tunnel heal failed for node %s: %s", nid, exc)


def _stop_locked(node_id: int) -> None:
    tun = _tunnels.pop(node_id, None)
    if not tun:
        return
    _kill_proc(tun.proc)
    if tun.key_path:
        try:
            os.unlink(tun.key_path)
        except OSError:
            pass


def _kill_proc(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
