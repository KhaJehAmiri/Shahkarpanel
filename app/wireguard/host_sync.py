"""Apply WireGuard peer specs to the panel host (tunnel exit side).

When a tunnel's exit is the panel (``exit_node_id is NULL``) and the relay
delegates native WireGuard to Xray dokodemo capture, peers must live on the
panel host's kernel ``wg0`` — not on the relay node. This module reuses the
node agent's declarative ``WireGuardManager`` against the host network
namespace (``network_mode: host``).
"""
from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("nexus-wg")


def _panel_container_id() -> Optional[str]:
    try:
        from app.xray.core import XRayCore

        return XRayCore._self_container_id()
    except Exception:
        return None


class _HostCommandRunner:
    """Run ``wg``/``awg``/``ip``/``iptables`` commands on the panel host.

    The panel runs unprivileged (``runuser -u nexuspanel``); the container was
    granted ``CAP_NET_ADMIN`` but a non-root process can't use it, so mutating
    the host WireGuard interface fails with "Operation not permitted" (the
    recurring ``WireGuard apply for wg0 failed`` warnings). When a direct call
    hits a permission error we escalate via ``docker exec --user root`` on this
    same container through the mounted docker.sock — the identical pattern used
    for privileged process cleanup in ``app.xray.core`` and for reading host WG
    transfer counters above — and remember the decision so later commands go
    straight to the escalated path.

    Signature matches ``WireGuardManager``'s injectable runner:
    ``run(cmd, input=None, check=True) -> CompletedProcess``.
    """

    def __init__(self) -> None:
        # Host WG mutation (ip link/address, wg syncconf, iptables) needs root.
        # The panel runs as a non-root user, so escalate every command when we
        # are not root. Deciding purely on euid — instead of probing per command
        # — avoids a false "direct works" verdict from read-only commands (e.g.
        # `ip link show`) that succeed for non-root while the mutations that
        # follow silently fail.
        self._escalate = os.geteuid() != 0
        self._cid: Optional[str] = None
        self._cid_resolved = False

    def _container_id(self) -> Optional[str]:
        if not self._cid_resolved:
            self._cid = _panel_container_id()
            self._cid_resolved = True
        return self._cid

    @staticmethod
    def _direct(cmd, input=None, check=True):
        return subprocess.run(
            cmd, input=input, text=True, capture_output=True, check=check
        )

    def _escalated(self, cmd, cid, input=None, check=True):
        # -i keeps stdin open so `wg syncconf <iface> /dev/stdin` reads `input`.
        full = ["docker", "exec", "--user", "root", "-i", cid, *cmd]
        return subprocess.run(
            full, input=input, text=True, capture_output=True, check=check
        )

    def __call__(self, cmd, input=None, check=True):
        if self._escalate:
            cid = self._container_id()
            if cid:
                return self._escalated(cmd, cid, input=input, check=check)
            # No escalation target (docker.sock unavailable): best-effort direct
            # so read-only commands still work rather than crashing the sync.
        return self._direct(cmd, input=input, check=check)


# One runner instance so the escalate decision + container id are cached across
# applies instead of being re-probed on every sync.
_host_command_runner = _HostCommandRunner()


def _load_host_wireguard_manager():
    """Import ``node.wireguard.WireGuardManager`` without the full node agent."""
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    cfg = types.ModuleType("config")
    log = types.ModuleType("logger")
    log.logger = logger
    old_cfg, old_log = sys.modules.get("config"), sys.modules.get("logger")
    sys.modules["config"] = cfg
    sys.modules["logger"] = log
    sys.modules.pop("wireguard", None)
    try:
        spec = importlib.util.spec_from_file_location("wireguard", root / "node" / "wireguard.py")
        if spec is None or spec.loader is None:
            raise ImportError("cannot load node/wireguard.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["wireguard"] = mod
        spec.loader.exec_module(mod)
        return mod.WireGuardManager, mod.WireGuardSpec
    finally:
        if old_cfg is not None:
            sys.modules["config"] = old_cfg
        elif "config" in sys.modules and sys.modules["config"] is cfg:
            del sys.modules["config"]
        if old_log is not None:
            sys.modules["logger"] = old_log
        elif "logger" in sys.modules and sys.modules["logger"] is log:
            del sys.modules["logger"]


_host_manager_cls = None


def _build_host_manager(base_cls):
    """Instantiate a panel-host ``WireGuardManager`` with the root-escalating
    runner and AWG detection corrected for the panel host.

    Two host-specific concerns, neither of which should change node behaviour:

    * ``run=_host_command_runner`` — the panel process is unprivileged, so every
      mutating ``wg``/``ip`` command is escalated via ``docker exec --user root``.
    * ``_interface_is_userspace_awg`` is overridden to rely *only* on live
      ``amneziawg-go`` daemon detection. The base method's fallback returns True
      for any interface that merely has a listen-port — which every plain kernel
      ``wg`` interface does. On the panel host (no ``awg``/``amneziawg-go``
      binaries, ``amnezia_available()`` is False) that false positive drives
      ``ensure_interface`` into the "want plain but currently AWG" branch, tearing
      the interface down and recreating it on *every* sync. That reset the per-peer
      transfer counters (breaking usage deltas / online tracking) and dropped every
      live session each time. Detecting AWG by the daemon alone keeps a healthy
      plain interface untouched so ``wg syncconf`` applies peers in place.
    """
    global _host_manager_cls
    if _host_manager_cls is None or _host_manager_cls.__base__ is not base_cls:

        class _HostWireGuardManager(base_cls):
            def _interface_is_userspace_awg(self, interface: str) -> bool:
                return self._awg_daemon_running(interface)

        _host_manager_cls = _HostWireGuardManager
    return _host_manager_cls(run=_host_command_runner)


def host_wireguard_available() -> bool:
    try:
        WireGuardManager, _ = _load_host_wireguard_manager()
        return WireGuardManager().available()
    except Exception:
        return False


def apply_host_wireguard_specs(specs: List[dict]) -> bool:
    """Best-effort apply of declarative WG specs on the panel host."""
    if not specs:
        return False
    try:
        WireGuardManager, WireGuardSpec = _load_host_wireguard_manager()
        mgr = _build_host_manager(WireGuardManager)
        if not mgr.available():
            logger.warning("host WireGuard sync skipped: wg/ip tools unavailable on panel host")
            return False
        parsed = [WireGuardSpec.from_dict(s) for s in specs]
        mgr.apply_specs(parsed)
        return True
    except Exception as exc:
        logger.warning("host WireGuard sync failed: %s", exc)
        return False


def _parse_wg_transfer(output: str) -> dict:
    """Parse ``wg show <iface> transfer`` output → ``{pubkey: {"rx", "tx"}}``."""
    result: dict = {}
    for line in (output or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3:
            continue
        try:
            result[parts[0]] = {"rx": int(parts[1]), "tx": int(parts[2])}
        except ValueError:
            continue
    return result


def _wg_show_transfer_raw(interface: str) -> str:
    """Return raw ``wg show <iface> transfer`` output, escalating if needed.

    The panel runs unprivileged (``runuser -u nexuspanel``) while the host
    ``wg`` netlink API needs ``CAP_NET_ADMIN``, which a non-root process does
    not carry even though the container was granted it. The shared
    :data:`_host_command_runner` transparently falls back to ``docker exec
    --user root`` on this same container via the mounted docker.sock, so usage
    collection works without running the whole panel as root.
    """
    import shutil

    binary = "wg" if shutil.which("wg") else ("awg" if shutil.which("awg") else "wg")
    try:
        res = _host_command_runner([binary, "show", interface, "transfer"], check=False)
    except Exception as exc:
        logger.debug("host wg transfer read for %s failed: %s", interface, exc)
        return ""
    if res.returncode != 0:
        logger.debug(
            "host wg transfer read for %s rc=%s: %s",
            interface,
            res.returncode,
            (res.stderr or "").strip(),
        )
        return ""
    return res.stdout


def read_host_wireguard_transfer(interface: str) -> dict:
    """Read ``wg show <iface> transfer`` on the panel host.

    Returns ``{public_key: {"rx": int, "tx": int}}`` (cumulative byte counters),
    or ``{}`` when the interface is absent / the tools are unavailable. This is
    the read-side counterpart to :func:`apply_host_wireguard_specs`: when the
    panel itself is the tunnel WireGuard exit, user traffic exits via the panel
    host's kernel interface, so its per-peer counters must be collected here —
    the node usage collector only sees remote WireGuard nodes.
    """
    if not interface:
        return {}
    return _parse_wg_transfer(_wg_show_transfer_raw(interface))


def sync_panel_exit_wireguard(db, *, peers: Optional[list] = None) -> bool:
    """Push peers to the panel host WG interface when it terminates tunneled WG."""
    from app.tunnel.relay import canonical_panel_exit_wireguard, panel_tunnel_exit_active
    from app.wireguard.operations import collect_wg_peers
    from app.wireguard.sync import build_node_specs, plain_wg_enabled

    if not panel_tunnel_exit_active(db):
        return False

    cfg = canonical_panel_exit_wireguard(db)
    if cfg is None or not plain_wg_enabled(cfg):
        return False

    if peers is None:
        peers = collect_wg_peers(db)

    specs = build_node_specs(cfg, peers)
    if not specs:
        return False

    ok = apply_host_wireguard_specs(specs)
    if ok:
        logger.info(
            "WireGuard peers synced to panel host (%s:%s)",
            cfg.interface,
            cfg.listen_port,
        )
    return ok
