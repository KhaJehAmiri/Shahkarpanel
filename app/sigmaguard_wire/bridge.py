"""Load SigmaGuard Wire presets and build Client API configs."""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from app import feature_flags

def _wire_root() -> Path:
    env = os.environ.get("SIGMAGUARD_WIRE_ROOT")
    if env:
        return Path(env)
    for candidate in (Path("/opt/sigmaguard/wire"), Path("/opt/sigmaguard-wire")):
        if (candidate / "presets" / "sigma_preset.py").is_file():
            return candidate
    return Path("/opt/sigmaguard/wire")


_ROOT = _wire_root()
AwgValue = Union[int, str]

# `_load_sigma_module()` is on the hot path (`/client/config`, `is_available()`
# gates on nearly every request when the flag is on). Re-parsing and
# re-`exec_module`-ing the preset file on every single call was wasteful
# (AUDIT_FINDINGS.md M3). Cache the loaded module keyed by the file's mtime so
# a hot-swapped preset file is still picked up without a panel restart.
_sigma_module_cache: Optional[Tuple[float, object]] = None
_sigma_module_cache_lock = threading.Lock()


def _load_sigma_module():
    global _sigma_module_cache

    path = _ROOT / "presets" / "sigma_preset.py"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    with _sigma_module_cache_lock:
        if _sigma_module_cache is not None and _sigma_module_cache[0] == mtime:
            return _sigma_module_cache[1]

        spec = importlib.util.spec_from_file_location("sg_wire_sigma_preset", path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _sigma_module_cache = (mtime, mod)
        return mod


def is_available() -> bool:
    """True when feature flag is on and preset module exists on disk."""
    if not feature_flags.is_enabled("sigmaguard_wire"):
        return False
    return _load_sigma_module() is not None


def default_preset() -> Dict[str, int]:
    mod = _load_sigma_module()
    if mod is None:
        return {}
    return dict(mod.default_deploy_preset())


def apply_preset_to_node(cfg) -> None:
    """Copy the deployment SigmaGuard preset into node_wireguard awg_* fields."""
    mod = _load_sigma_module()
    if mod is None:
        raise ValueError("SigmaGuard Wire preset module not found")
    preset = mod.default_deploy_preset()
    for db_key, val in preset.items():
        if db_key == "preset_rev":
            cfg.sg_wire_preset_rev = str(val)
        else:
            setattr(cfg, db_key, val)


def awg_params_for_node(cfg) -> Dict[str, AwgValue]:
    """Server-synced params from DB + client-only keys when sg_wire is active."""
    from app.wireguard.sync import awg_params_from_cfg, sg_wire_enabled

    params: Dict[str, AwgValue] = dict(awg_params_from_cfg(cfg))
    if sg_wire_enabled(cfg):
        mod = _load_sigma_module()
        if mod is not None and hasattr(mod, "client_only_params"):
            params.update(mod.client_only_params())
    return params


def preset_rev_for_node(cfg) -> str:
    rev = getattr(cfg, "sg_wire_preset_rev", None) if cfg else None
    if rev:
        return str(rev)
    p = default_preset()
    return str(p.get("preset_rev", ""))


def preset_rev() -> str:
    return preset_rev_for_node(None) or str(default_preset().get("preset_rev", ""))


def awg_params_for_conf() -> Dict[str, AwgValue]:
    """Legacy helper — prefer ``awg_params_for_node(cfg)`` after node sync."""
    mod = _load_sigma_module()
    if mod is None:
        return {}
    preset = mod.default_deploy_preset()
    params: Dict[str, AwgValue] = dict(mod.awg_interface_params(preset))
    if hasattr(mod, "client_only_params"):
        params.update(mod.client_only_params())
    return params


def build_client_conf(
    user_settings: dict,
    dbnode,
    *,
    dns: Optional[str] = None,
    include_i1: bool = True,
) -> Optional[str]:
    """Render wg-quick text using the node's synced SigmaGuard Wire preset."""
    from app.subscription.wireguard import render_wireguard_conf, node_endpoint
    from app.wireguard.sync import amneziawg_enabled, sg_wire_enabled

    cfg = dbnode.wireguard
    if cfg is None or not amneziawg_enabled(cfg) or not sg_wire_enabled(cfg):
        return None
    private_key = user_settings.get("private_key")
    address = user_settings.get("awg_address") or user_settings.get("sg_wire_address")
    if not private_key or not address:
        return None
    amnezia = awg_params_for_node(cfg)
    if not amnezia:
        return None
    if not include_i1:
        # Legacy iOS Amnezia builds ignore I1; subscription exports keep it by default.
        amnezia = {k: v for k, v in amnezia.items() if k != "I1"}
    from app.wireguard.awg import AWG_RECOMMENDED_MTU

    return render_wireguard_conf(
        private_key=private_key,
        address=address,
        server_public_key=cfg.awg_public_key,
        endpoint=node_endpoint(dbnode, variant="awg"),
        dns=dns or cfg.dns or "1.1.1.1, 8.8.8.8",
        preshared_key=user_settings.get("preshared_key"),
        mtu=AWG_RECOMMENDED_MTU,
        amnezia=amnezia,
    )
