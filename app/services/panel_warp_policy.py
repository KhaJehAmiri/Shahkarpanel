"""Install the per-node WARP split on the panel's own Xray core.

WARP policy is applied in ``build_node_xray_config`` for exit/relay nodes.
Clients that hit the panel directly (CDN / ``in1`` on the panel host) never
see those node configs, so Google/YouTube/AI stayed on the datacenter IP even
when every tun node had ``warp_mode=sensitive``. This reapplies the same
domain list on the local core at start/restart.
"""
from __future__ import annotations

from copy import deepcopy

from app import logger


def _already_has_panel_warp(config) -> bool:
    """True when domain→WARP split is already in this payload (skip deepcopy)."""
    obs = config.get("outbounds") or []
    if not any(
        isinstance(o, dict)
        and str(o.get("protocol") or "") == "wireguard"
        and str(o.get("tag") or "").startswith("warp")
        for o in obs
    ):
        return False
    for rule in ((config.get("routing") or {}).get("rules") or []):
        if not isinstance(rule, dict):
            continue
        domains = rule.get("domain") or []
        if any("google.com" in str(d) for d in domains):
            return True
    return False


def apply_local_core_warp_policy(config):
    """Fold sensitive (or full) WARP exit into the panel-local Xray config."""
    if _already_has_panel_warp(config):
        return config

    try:
        from app.db import GetDB
        from app.db.models import Node
        from app.utils import warp as warp_util
        from app.xray.warp_routing import (
            ensure_tunnel_exit_sniffing,
            ensure_warp_exit,
            ensure_warp_sensitive_exit,
            parse_warp_tags,
            refresh_sensitive_quic_block,
        )

        with GetDB() as db:
            nodes = (
                db.query(Node)
                .filter(Node.warp_enabled.is_(True))
                .all()
            )
        if not nodes:
            return config

        tags: list[str] = []
        seen: set[str] = set()
        sensitive = False
        for node in nodes:
            mode = str(getattr(node, "warp_mode", None) or "full").strip().lower()
            if mode == "sensitive":
                sensitive = True
            for tag in parse_warp_tags(getattr(node, "warp_tag", None)):
                if tag in seen:
                    continue
                seen.add(tag)
                tags.append(tag)

        outbounds: list[dict] = []
        for tag in tags:
            account = warp_util.get_warp(tag)
            outbound = (account or {}).get("outbound") if account else None
            if isinstance(outbound, dict):
                outbounds.append(outbound)
            else:
                logger.warning("Panel local WARP: missing account for tag %s", tag)
        if not outbounds:
            return config

        try:
            result = config.copy() if hasattr(config, "copy") else deepcopy(dict(config))
        except Exception:
            return config

        data = dict(result)
        if sensitive:
            data = ensure_warp_sensitive_exit(data, outbounds)
            data = ensure_tunnel_exit_sniffing(data)
            data = refresh_sensitive_quic_block(data)
            logger.info(
                "Panel local core: sensitive WARP split tags=%s",
                ",".join(str(o.get("tag") or "") for o in outbounds),
            )
        else:
            data = ensure_warp_exit(data, outbounds[0], as_default_exit=True)
            for extra in outbounds[1:]:
                data = ensure_warp_exit(data, extra, as_default_exit=False)
            logger.info(
                "Panel local core: full WARP exit tag=%s",
                outbounds[0].get("tag"),
            )

        if hasattr(result, "clear") and hasattr(result, "update"):
            result.clear()
            result.update(data)
            return result
        return data
    except Exception:
        logger.exception("Panel local WARP policy failed")
        return config
