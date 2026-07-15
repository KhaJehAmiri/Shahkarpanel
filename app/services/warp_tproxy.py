"""Transparent proxy (TPROXY) so kernel WireGuard clients exit via Xray WARP.

Cloudflare WARP needs the ``reserved`` WireGuard field, which only Xray's
userspace outbound supports — so Amnezia/plain WG cannot speak WARP directly.
Instead we divert client packets into a dokodemo-door inbound and route that
to the WARP outbound.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional, Sequence


def warp_tproxy_port(node_id: int) -> int:
    return 22000 + (int(node_id) % 1000)


def warp_tproxy_inbound_tag(node_id: int) -> str:
    return f"node-{int(node_id)}-warp-tproxy"


def warp_tproxy_mark() -> int:
    return 0x18E70  # 102000


def warp_tproxy_table() -> int:
    return 51829


def build_warp_tproxy_dokodemo(node_id: int) -> dict[str, Any]:
    """dokodemo-door inbound that accepts TPROXY redirects from WG ifaces."""
    return {
        "tag": warp_tproxy_inbound_tag(node_id),
        "listen": "0.0.0.0",
        "port": warp_tproxy_port(node_id),
        "protocol": "dokodemo-door",
        "settings": {
            "network": "tcp,udp",
            "followRedirect": True,
        },
        "streamSettings": {
            "sockopt": {
                "tproxy": "tproxy",
            }
        },
    }


def inject_warp_tproxy_inbound(
    payload: dict[str, Any],
    node_id: int,
    outbound_tag: str,
) -> dict[str, Any]:
    """Ensure dokodemo inbound + inbound→WARP rule exist."""
    data = deepcopy(payload)
    tag = warp_tproxy_inbound_tag(node_id)
    inbound = build_warp_tproxy_dokodemo(node_id)
    inbounds = [ib for ib in list(data.get("inbounds") or []) if not (
        isinstance(ib, dict) and ib.get("tag") == tag
    )]
    inbounds.append(inbound)
    data["inbounds"] = inbounds

    routing = data.setdefault("routing", {"domainStrategy": "IPIfNonMatch", "rules": []})
    rules = [
        r for r in list(routing.get("rules") or [])
        if not (
            isinstance(r, dict)
            and tag in (r.get("inboundTag") or [])
        )
    ]
    rules.insert(0, {
        "type": "field",
        "inboundTag": [tag],
        "outboundTag": outbound_tag,
    })
    routing["rules"] = rules
    return data


def strip_warp_tproxy_inbound(payload: dict[str, Any], node_id: int) -> dict[str, Any]:
    data = deepcopy(payload)
    tag = warp_tproxy_inbound_tag(node_id)
    data["inbounds"] = [
        ib for ib in list(data.get("inbounds") or [])
        if not (isinstance(ib, dict) and ib.get("tag") == tag)
    ]
    routing = data.get("routing")
    if isinstance(routing, dict):
        routing["rules"] = [
            r for r in list(routing.get("rules") or [])
            if not (
                isinstance(r, dict)
                and tag in (r.get("inboundTag") or [])
            )
        ]
    return data


def retarget_xray_wg_to_warp(
    payload: dict[str, Any],
    node_id: int,
    outbound_tag: str,
) -> dict[str, Any]:
    """Point ``node-{id}-xray-wg-in`` routing at WARP instead of DIRECT."""
    from app.wireguard.xray_native import xray_wg_inbound_tag

    data = deepcopy(payload)
    tag = xray_wg_inbound_tag(node_id)
    routing = data.get("routing")
    if not isinstance(routing, dict):
        return data
    rules = list(routing.get("rules") or [])
    found = False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if tag in (rule.get("inboundTag") or []):
            rule["outboundTag"] = outbound_tag
            found = True
    if not found:
        rules.insert(0, {
            "type": "field",
            "inboundTag": [tag],
            "outboundTag": outbound_tag,
        })
    routing["rules"] = rules
    return data


def node_wg_client_subnets(dbnode) -> list[str]:
    """Subnets whose traffic should be diverted into WARP TPROXY."""
    cfg = getattr(dbnode, "wireguard", None)
    if cfg is None:
        return []
    out: list[str] = []
    for attr in ("subnet", "awg_subnet"):
        val = getattr(cfg, attr, None)
        if val:
            out.append(str(val))
    return out


def node_wg_client_interfaces(dbnode) -> list[str]:
    cfg = getattr(dbnode, "wireguard", None)
    if cfg is None:
        return []
    out: list[str] = []
    if getattr(cfg, "plain_enabled", True) and getattr(cfg, "interface", None):
        out.append(str(cfg.interface))
    if getattr(cfg, "awg_enabled", False) and getattr(cfg, "awg_interface", None):
        out.append(str(cfg.awg_interface))
    return out
