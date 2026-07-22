"""Build per-protocol connection material for the SigmaGuard client API."""
from typing import Any, Dict, List, Optional

from app.models.proxy import ProxyTypes
from app.subscription.quic import (
    filter_singbox_client_entry_nodes,
    user_anytls_link,
    user_hysteria2_link,
    user_tuic_link,
)
from app.subscription.region_display import node_config_remark
from app.subscription.wireguard import user_config as build_wireguard_user_config
from app.tls.inspect import cert_requires_insecure


def _proxy_settings(dbuser, proxy_type: ProxyTypes) -> Optional[dict]:
    for proxy in dbuser.proxies:
        if proxy.type is proxy_type:
            return proxy.settings or {}
    return None


def _node_by_id(nodes: List, node_id: Optional[int]):
    """Resolve an explicit node preference against a candidate list.

    ``node_id is None`` means "no preference" and defaults to the first
    candidate. An explicit ``node_id`` that isn't in ``nodes`` must return
    ``None`` rather than silently substituting an arbitrary node — callers
    then correctly omit that protocol instead of serving it from the wrong
    node (see AUDIT_FINDINGS.md H3: this used to defeat the trader
    dedicated-IP guarantee whenever the bound node didn't carry a protocol).
    """
    if node_id is None:
        return nodes[0] if nodes else None
    return next((n for n in nodes if n.id == node_id), None)


def _wg_conf(db, dbuser, dbnode, variant: str) -> Optional[str]:
    from app.wireguard.operations import ensure_preshared_key, ensure_user_address
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

    settings = _proxy_settings(dbuser, ProxyTypes.WireGuard)
    if not settings or dbnode.wireguard is None:
        return None
    cfg = dbnode.wireguard
    for proxy in dbuser.proxies:
        if proxy.type is ProxyTypes.WireGuard:
            if variant == "awg" and amneziawg_enabled(cfg):
                # AmneziaVPN on iOS requires a PSK; subscription export already
                # calls ensure_preshared_key — Client API must do the same (M10).
                settings = ensure_preshared_key(db, proxy)
                if not settings.get("awg_address"):
                    ensure_user_address(db, proxy, cfg.awg_subnet, cfg=cfg)
            elif plain_wg_enabled(cfg) and not settings.get("address"):
                ensure_user_address(db, proxy, cfg.subnet, cfg=cfg)
            settings = proxy.settings or {}
            break
    return build_wireguard_user_config(settings, dbnode, variant=variant)


def _singbox_insecure(cfg) -> bool:
    if cfg is None:
        return True
    return cert_requires_insecure(
        tls_trusted=getattr(cfg, "tls_trusted", False),
        sni=cfg.sni,
    )


def build_materials(
    db,
    dbuser,
    *,
    protocols: List[str],
    protocol_nodes: Optional[Dict[str, Optional[int]]] = None,
    structured_xray: Optional[List[dict]] = None,
    v2ray_links: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return a dict keyed by engine protocol name with connection payloads."""
    from app.db import crud
    from app.client.xray_structured import entries_for_protocol

    materials: Dict[str, Any] = {}
    protocol_nodes = protocol_nodes or {}
    structured_xray = structured_xray or []
    v2ray_links = v2ray_links or []

    wg_nodes = [n for n in crud.get_wireguard_nodes(db) if n.wireguard is not None]
    sb_nodes = filter_singbox_client_entry_nodes(
        db,
        [
            n for n in crud.get_singbox_nodes(db)
            if n.singbox and (
                n.singbox.hysteria2_enabled or n.singbox.tuic_enabled or n.singbox.anytls_enabled
            )
        ],
    )

    if "wireguard" in protocols:
        nid = protocol_nodes.get("wireguard")
        wg_node = _node_by_id(wg_nodes, nid)
        if wg_node:
            conf = _wg_conf(db, dbuser, wg_node, "plain")
            if conf:
                materials["wireguard"] = {
                    "node_id": wg_node.id,
                    "node_name": wg_node.name,
                    "conf": conf,
                }

    if "amneziawg" in protocols:
        nid = protocol_nodes.get("amneziawg")
        wg_node = _node_by_id(wg_nodes, nid)
        if wg_node:
            conf = _wg_conf(db, dbuser, wg_node, "awg")
            if conf:
                materials["amneziawg"] = {
                    "node_id": wg_node.id,
                    "node_name": wg_node.name,
                    "conf": conf,
                }

    if "sigmaguard-wire" in protocols:
        from app.sigmaguard_wire.bridge import build_client_conf, is_available, preset_rev_for_node
        from app.wireguard.sync import amneziawg_enabled, sg_wire_enabled

        if is_available():
            sg_nodes = [
                n for n in wg_nodes
                if n.wireguard and amneziawg_enabled(n.wireguard) and sg_wire_enabled(n.wireguard)
            ]
            nid = protocol_nodes.get("sigmaguard-wire") or protocol_nodes.get("amneziawg")
            wg_node = _node_by_id(sg_nodes or wg_nodes, nid)
            if wg_node and wg_node.wireguard and sg_wire_enabled(wg_node.wireguard):
                from app.wireguard.operations import ensure_preshared_key, ensure_user_address

                settings = _proxy_settings(dbuser, ProxyTypes.WireGuard)
                if settings and wg_node.wireguard and amneziawg_enabled(wg_node.wireguard):
                    for proxy in dbuser.proxies:
                        if proxy.type is ProxyTypes.WireGuard:
                            settings = ensure_preshared_key(db, proxy)
                            if not settings.get("awg_address"):
                                ensure_user_address(
                                    db, proxy, wg_node.wireguard.awg_subnet, cfg=wg_node.wireguard
                                )
                            settings = proxy.settings or {}
                            break
                    conf = build_client_conf(settings, wg_node)
                    if conf:
                        materials["sigmaguard-wire"] = {
                            "node_id": wg_node.id,
                            "node_name": wg_node.name,
                            "conf": conf,
                            "preset_rev": preset_rev_for_node(wg_node.wireguard),
                            "engine": "sigmaguard-wire",
                        }

    hy2_settings = _proxy_settings(dbuser, ProxyTypes.Hysteria2)
    if "hysteria2" in protocols and hy2_settings:
        nid = protocol_nodes.get("hysteria2")
        sb_node = _node_by_id(sb_nodes, nid)
        if sb_node and sb_node.singbox and sb_node.singbox.hysteria2_enabled:
            link = user_hysteria2_link(
                hy2_settings,
                sb_node,
                remark=node_config_remark(sb_node, "Hysteria2"),
                insecure=_singbox_insecure(sb_node.singbox),
                speed_limit_up=dbuser.speed_limit_up,
                speed_limit_down=dbuser.speed_limit_down,
            )
            if link:
                materials["hysteria2"] = {
                    "node_id": sb_node.id,
                    "node_name": sb_node.name,
                    "link": link,
                    "tls_trusted": not _singbox_insecure(sb_node.singbox),
                }

    tuic_settings = _proxy_settings(dbuser, ProxyTypes.TUIC)
    if "tuic" in protocols and tuic_settings:
        nid = protocol_nodes.get("tuic")
        sb_node = _node_by_id(sb_nodes, nid)
        if sb_node and sb_node.singbox and sb_node.singbox.tuic_enabled:
            link = user_tuic_link(
                tuic_settings,
                sb_node,
                remark=node_config_remark(sb_node, "TUIC"),
                insecure=_singbox_insecure(sb_node.singbox),
                speed_limit_up=dbuser.speed_limit_up,
                speed_limit_down=dbuser.speed_limit_down,
            )
            if link:
                materials["tuic"] = {
                    "node_id": sb_node.id,
                    "node_name": sb_node.name,
                    "link": link,
                    "tls_trusted": not _singbox_insecure(sb_node.singbox),
                }

    anytls_settings = _proxy_settings(dbuser, ProxyTypes.AnyTLS)
    if "anytls" in protocols and anytls_settings:
        nid = protocol_nodes.get("anytls")
        sb_node = _node_by_id(sb_nodes, nid)
        if sb_node and sb_node.singbox and sb_node.singbox.anytls_enabled:
            link = user_anytls_link(
                anytls_settings,
                sb_node,
                remark=node_config_remark(sb_node, "AnyTLS"),
                insecure=_singbox_insecure(sb_node.singbox),
                speed_limit_up=dbuser.speed_limit_up,
                speed_limit_down=dbuser.speed_limit_down,
            )
            if link:
                materials["anytls"] = {
                    "node_id": sb_node.id,
                    "node_name": sb_node.name,
                    "link": link,
                    "tls_trusted": not _singbox_insecure(sb_node.singbox),
                }

    reality_entries = entries_for_protocol(structured_xray, "vless-reality")
    if "vless-reality" in protocols and reality_entries:
        materials["vless-reality"] = {"outbounds": reality_entries}

    ss_entries = entries_for_protocol(structured_xray, "shadowsocks-2022")
    if "shadowsocks-2022" in protocols and ss_entries:
        materials["shadowsocks-2022"] = {"outbounds": ss_entries}

    cdn_entries = entries_for_protocol(structured_xray, "cdn")
    if "cdn" in protocols and cdn_entries:
        materials["cdn"] = {"outbounds": cdn_entries}

    return materials
