"""Panel-host WARP egress for tunnel exits (relay → panel WG → internet).

When a relay has ``warp_enabled`` but WireGuard is tunnelled to the panel,
client packets exit via the panel host. We route those client subnets through
a kernel WireGuard interface (``nxwarp0``) bound to the Cloudflare WARP
account — see ``panel_warp_wg``.
"""
from __future__ import annotations

from app import logger
from app.services.panel_warp_wg import apply_panel_warp_wg
from app.services.warp_tproxy import node_wg_client_subnets


def _panel_exit_warp_nodes(db) -> list:
    from app.db import models
    from app.tunnel.relay import _tunnel_relay_index

    index = _tunnel_relay_index(db)
    nodes = db.query(models.Node).filter(models.Node.warp_enabled.is_(True)).all()
    return [n for n in nodes if int(n.id) in index.panel_exit_relays]


def _collect_subnets(nodes) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in nodes:
        for s in node_wg_client_subnets(n):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _pick_warp_tag(nodes) -> str:
    for n in nodes:
        return (getattr(n, "warp_tag", None) or "warp").strip() or "warp"
    return "warp"


def _warp_credentials(tag: str) -> dict | None:
    from app.utils import warp as warp_util

    account = warp_util.get_warp(tag)
    outbound = (account or {}).get("outbound") if account else None
    if not isinstance(outbound, dict):
        return None
    settings = outbound.get("settings") or {}
    peers = settings.get("peers") or []
    if not peers or not isinstance(peers[0], dict):
        return None
    addresses = settings.get("address") or ["172.16.0.2/32"]
    v4 = next((a for a in addresses if ":" not in str(a)), addresses[0])
    return {
        "private_key": str(settings.get("secretKey") or ""),
        "address": str(v4),
        "peer_public": str(peers[0].get("publicKey") or ""),
        "endpoint": str(peers[0].get("endpoint") or ""),
    }


def sync_panel_warp_egress(db) -> dict:
    nodes = _panel_exit_warp_nodes(db)
    subnets = _collect_subnets(nodes)
    enabled = bool(nodes) and bool(subnets)

    ok = False
    if not enabled:
        ok = apply_panel_warp_wg(enabled=False, subnets=[])
    else:
        tag = _pick_warp_tag(nodes)
        creds = _warp_credentials(tag)
        if not creds:
            logger.warning("Panel WARP egress: missing account for tag=%s", tag)
            ok = False
        else:
            ok = apply_panel_warp_wg(
                enabled=True,
                subnets=subnets,
                private_key=creds["private_key"],
                address=creds["address"],
                peer_public=creds["peer_public"],
                endpoint=creds["endpoint"],
            )

    # Restart local Xray so apply_endpoint_tunnels re-pins tunnel-*-exit → WARP
    # for Xray / sing-box traffic that arrives via the relay tunnel.
    core_ok = False
    try:
        from app import xray

        cfg = xray.config.include_db_users()
        xray.core.restart(cfg)
        core_ok = bool(getattr(xray.core, "started", False))
    except Exception:
        logger.exception("Panel Xray restart for tunnel WARP exit failed")

    try:
        from app.services.panel_warp_tproxy_host import apply_warp_tproxy

        apply_warp_tproxy(enabled=False, subnets=[], port=22000)
    except Exception:
        pass

    logger.info(
        "Panel WARP egress: enabled=%s nodes=%s subnets=%s wg_ok=%s core_ok=%s",
        enabled,
        [n.id for n in nodes],
        subnets,
        ok,
        core_ok,
    )
    return {
        "enabled": enabled,
        "nodes": [n.id for n in nodes],
        "subnets": subnets,
        "ok": ok,
        "core_ok": core_ok,
    }
