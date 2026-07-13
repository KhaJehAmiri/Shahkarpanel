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
import sys
import types
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("nexus-wg")


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
        mgr = WireGuardManager()
        if not mgr.available():
            logger.warning("host WireGuard sync skipped: wg/ip tools unavailable on panel host")
            return False
        parsed = [WireGuardSpec.from_dict(s) for s in specs]
        mgr.apply_specs(parsed)
        return True
    except Exception as exc:
        logger.warning("host WireGuard sync failed: %s", exc)
        return False


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
