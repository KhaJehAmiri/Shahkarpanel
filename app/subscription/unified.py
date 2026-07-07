"""Merge WireGuard / QUIC product protocols into unified subscriptions."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional
from urllib import parse

import yaml

from app.models.proxy import ProxyTypes
from app.services.node_pick import pick_node
from app.singbox.quality import hysteria2_outbound_quality, tuic_outbound_quality
from app.singbox.speed import speed_tier
from app.subscription.quic import (
    singbox_link_insecure,
    user_anytls_link,
    user_hysteria2_link,
    user_tuic_link,
)
from app.subscription.wireguard import node_endpoint, user_config

if TYPE_CHECKING:
    from app.models.user import UserResponse


def _client_settings(user: "UserResponse", ptype: ProxyTypes) -> dict:
    proxy = (user.proxies or {}).get(ptype)
    if proxy is None:
        return {}
    if hasattr(proxy, "model_dump"):
        return proxy.model_dump(mode="json")
    if isinstance(proxy, dict):
        return proxy
    return {}


def _wireguard_server_public_key(wg_node, *, variant: str) -> str:
    if variant == "awg":
        return wg_node.wireguard.awg_public_key
    return wg_node.wireguard.public_key


def _xray_wireguard_outbound(
    *,
    tag: str,
    settings: dict,
    wg_node,
    host: str,
    port: int,
    local_addr: str,
    variant: str,
) -> dict:
    from app.subscription.wireguard import DEFAULT_KEEPALIVE

    peer = {
        "publicKey": _wireguard_server_public_key(wg_node, variant=variant),
        "endpoint": f"{host}:{port}",
        "keepAlive": DEFAULT_KEEPALIVE,
        "allowedIPs": ["0.0.0.0/0"],
    }
    if settings.get("preshared_key"):
        peer["preSharedKey"] = settings["preshared_key"]
    return {
        "tag": tag,
        "protocol": "wireguard",
        "settings": {
            "secretKey": settings.get("private_key"),
            "address": [local_addr] if local_addr else [],
            "mtu": wg_node.wireguard.mtu or 1420,
            "peers": [peer],
        },
    }


def _clash_wireguard_proxy(
    *,
    tag: str,
    settings: dict,
    wg_node,
    host: str,
    port: int,
    local_addr: str,
    variant: str,
) -> dict:
    from app.subscription.wireguard import DEFAULT_KEEPALIVE

    proxy = {
        "name": tag,
        "type": "wireguard",
        "server": host,
        "port": port,
        "private-key": settings.get("private_key"),
        "public-key": _wireguard_server_public_key(wg_node, variant=variant),
        "ip": local_addr,
        "allowed-ips": ["0.0.0.0/0"],
        "udp": True,
        "persistent-keepalive": DEFAULT_KEEPALIVE,
        "mtu": wg_node.wireguard.mtu or 1420,
    }
    if settings.get("preshared_key"):
        proxy["pre-shared-key"] = settings["preshared_key"]
    return proxy


def _collect_wireguard_exports(user: "UserResponse", wg_nodes: list) -> list[tuple[str, str, object, dict, str, int, str]]:
    """Return (variant, tag, wg_node, settings, host, port, local_addr) tuples."""
    settings = _client_settings(user, ProxyTypes.WireGuard)
    wg = pick_node(wg_nodes)
    if not (wg and settings and wg.wireguard):
        return []
    exports: list[tuple[str, str, object, dict, str, int, str]] = []
    for variant in ("plain", "awg"):
        if not user_config(settings, wg, variant=variant):
            continue
        host, port_str = node_endpoint(wg, variant=variant).rsplit(":", 1)
        tag = f"wg-{wg.name}" + ("-awg" if variant == "awg" else "")
        addr = settings.get("awg_address" if variant == "awg" else "address") or ""
        exports.append((variant, tag, wg, settings, host, int(port_str), addr))
    return exports


def _singbox_tls(dbnode, host: str) -> dict:
    cfg = dbnode.singbox
    insecure = singbox_link_insecure(cfg)
    tls: dict = {"enabled": True, "server_name": (cfg.sni if cfg else None) or host}
    if insecure:
        tls["insecure"] = True
    return tls


def _refresh_singbox_selector_groups(data: dict) -> None:
    """Include QUIC/WG outbounds in selector/urltest after unified merge."""
    outbounds = data.get("outbounds") or []
    urltest_types = {
        "vmess", "vless", "trojan", "shadowsocks",
        "hysteria2", "tuic", "anytls",
    }
    selector_types = urltest_types | {"wireguard", "urltest"}
    urltest_tags = [
        o["tag"] for o in outbounds
        if o.get("tag") and o.get("type") in urltest_types
    ]
    selector_tags = [
        o["tag"] for o in outbounds
        if o.get("tag") and o.get("type") in selector_types
    ]
    for outbound in outbounds:
        if outbound.get("type") == "urltest":
            outbound["outbounds"] = urltest_tags
        elif outbound.get("type") == "selector":
            outbound["outbounds"] = selector_tags


def _append_singbox(user: "UserResponse", config_text: str) -> str:
    from app.db import GetDB, crud
    from app.models.node import NodeStatus

    data = json.loads(config_text)
    outbounds = list(data.get("outbounds") or [])
    tags = {o.get("tag") for o in outbounds if o.get("tag")}
    before = len(outbounds)

    with GetDB() as db:
        nodes = [
            n for n in crud.get_nodes(db)
            if n.status == NodeStatus.connected
        ]
        wg_nodes = [n for n in nodes if n.core_kind == "wireguard" or getattr(n, "wireguard", None)]
        sb_nodes = [n for n in nodes if getattr(n, "singbox", None)]

        # WireGuard → sing-box wireguard outbound
        if ProxyTypes.WireGuard in (user.proxies or {}):
            wg = pick_node(wg_nodes)
            settings = _client_settings(user, ProxyTypes.WireGuard)
            if wg and settings and wg.wireguard:
                for variant in ("plain", "awg"):
                    conf = user_config(settings, wg, variant=variant)
                    if not conf:
                        continue
                    host, port_str = node_endpoint(wg, variant=variant).rsplit(":", 1)
                    tag = f"wg-{wg.name}" + ("-awg" if variant == "awg" else "")
                    if tag in tags:
                        continue
                    addr = settings.get("awg_address" if variant == "awg" else "address") or ""
                    outbounds.append({
                        "type": "wireguard",
                        "tag": tag,
                        "server": host,
                        "server_port": int(port_str),
                        "local_address": [addr] if addr else [],
                        "private_key": settings.get("private_key"),
                        "peer_public_key": (
                            wg.wireguard.awg_public_key if variant == "awg"
                            else wg.wireguard.public_key
                        ),
                        "mtu": wg.wireguard.mtu or 1280,
                    })
                    if settings.get("preshared_key"):
                        outbounds[-1]["pre_shared_key"] = settings["preshared_key"]
                    tags.add(tag)
                    break

        settings = _client_settings(user, ProxyTypes.Hysteria2)
        if settings:
            node = pick_node(sb_nodes)
            if node and node.singbox and node.singbox.hysteria2_enabled:
                host = node.singbox.sni or node.address
                tag = f"hy2-{node.name}"
                if tag not in tags:
                    from app.singbox.sync import hysteria2_port_for_user

                    hy2_port = hysteria2_port_for_user(
                        int(node.singbox.hysteria2_port),
                        user.speed_limit_up,
                        user.speed_limit_down,
                    )
                    tier_limited = speed_tier(user.speed_limit_up, user.speed_limit_down) is not None
                    outbounds.append({
                        "type": "hysteria2",
                        "tag": tag,
                        "server": host,
                        "server_port": hy2_port,
                        "password": settings.get("password"),
                        "tls": _singbox_tls(node, host),
                        **hysteria2_outbound_quality(tier_limited=tier_limited),
                    })
                    if node.singbox.hysteria2_obfs_password:
                        outbounds[-1]["obfs"] = {
                            "type": "salamander",
                            "password": node.singbox.hysteria2_obfs_password,
                        }
                    tags.add(tag)

        settings = _client_settings(user, ProxyTypes.TUIC)
        if settings:
            node = pick_node(sb_nodes)
            if node and node.singbox and node.singbox.tuic_enabled:
                host = node.singbox.sni or node.address
                tag = f"tuic-{node.name}"
                if tag not in tags:
                    from app.singbox.sync import tuic_port_for_user

                    tuic_port = tuic_port_for_user(
                        int(node.singbox.tuic_port),
                        user.speed_limit_up,
                        user.speed_limit_down,
                    )
                    outbounds.append({
                        "type": "tuic",
                        "tag": tag,
                        "server": host,
                        "server_port": tuic_port,
                        "uuid": str(settings.get("uuid") or ""),
                        "password": settings.get("password"),
                        "tls": _singbox_tls(node, host),
                        **tuic_outbound_quality(
                            congestion_control=node.singbox.tuic_congestion_control or "bbr"
                        ),
                    })
                    tags.add(tag)

        settings = _client_settings(user, ProxyTypes.AnyTLS)
        if settings:
            node = pick_node(sb_nodes)
            if node and node.singbox and node.singbox.anytls_enabled:
                host = node.singbox.sni or node.address
                tag = f"anytls-{node.name}"
                if tag not in tags:
                    from app.singbox.sync import anytls_port_for_user

                    anytls_port = anytls_port_for_user(
                        int(node.singbox.anytls_port),
                        user.speed_limit_up,
                        user.speed_limit_down,
                    )
                    outbounds.append({
                        "type": "anytls",
                        "tag": tag,
                        "server": host,
                        "server_port": anytls_port,
                        "password": settings.get("password"),
                        "tls": _singbox_tls(node, host),
                    })
                    tags.add(tag)

    if len(outbounds) == before:
        return config_text
    data["outbounds"] = outbounds
    _refresh_singbox_selector_groups(data)
    return json.dumps(data, indent=4)


def _refresh_clash_proxy_groups(data: dict) -> None:
    """Include QUIC/WG proxies in selector/url-test groups after unified merge."""
    proxies = data.get("proxies") or []
    names = [p.get("name") for p in proxies if p.get("name")]
    if not names:
        return
    for group in data.get("proxy-groups") or []:
        gtype = (group.get("type") or "").lower()
        if gtype in ("select", "url-test", "fallback", "load-balance", "relay"):
            group["proxies"] = names


def _append_clash_meta(user: "UserResponse", config_text: str) -> str:
    from app.db import GetDB, crud
    from app.models.node import NodeStatus

    data = yaml.safe_load(config_text) or {}
    proxies = list(data.get("proxies") or [])
    names = {p.get("name") for p in proxies}
    before = len(proxies)

    with GetDB() as db:
        nodes = [n for n in crud.get_nodes(db) if n.status == NodeStatus.connected]
        sb_nodes = [n for n in nodes if getattr(n, "singbox", None)]
        wg_nodes = [n for n in nodes if n.core_kind == "wireguard" or getattr(n, "wireguard", None)]

        settings = _client_settings(user, ProxyTypes.Hysteria2)
        if settings:
            node = pick_node(sb_nodes)
            tag = f"hy2-{node.name}" if node else None
            link = user_hysteria2_link(
                settings, node, remark=tag,
                speed_limit_up=user.speed_limit_up,
                speed_limit_down=user.speed_limit_down,
            ) if node else None
            if link and tag and tag not in names:
                proxies.append(_clash_from_uri(link, tag, "hysteria2"))

        settings = _client_settings(user, ProxyTypes.TUIC)
        if settings:
            node = pick_node(sb_nodes)
            tag = f"tuic-{node.name}" if node else None
            link = user_tuic_link(
                settings, node, remark=tag,
                speed_limit_up=user.speed_limit_up,
                speed_limit_down=user.speed_limit_down,
            ) if node else None
            if link and tag and tag not in names:
                proxies.append(_clash_from_uri(link, tag, "tuic"))

        settings = _client_settings(user, ProxyTypes.AnyTLS)
        if settings:
            node = pick_node(sb_nodes)
            tag = f"anytls-{node.name}" if node else None
            link = user_anytls_link(
                settings, node, remark=tag,
                speed_limit_up=user.speed_limit_up,
                speed_limit_down=user.speed_limit_down,
            ) if node else None
            if link and tag and tag not in names:
                proxies.append(_clash_from_uri(link, tag, "anytls"))

        settings = _client_settings(user, ProxyTypes.WireGuard)
        if settings:
            wg = pick_node(wg_nodes)
            if wg and wg.wireguard:
                for variant, tag, wg_node, wg_settings, host, port, addr in _collect_wireguard_exports(
                    user, wg_nodes
                ):
                    if tag not in names:
                        proxies.append(
                            _clash_wireguard_proxy(
                                tag=tag,
                                settings=wg_settings,
                                wg_node=wg_node,
                                host=host,
                                port=port,
                                local_addr=addr,
                                variant=variant,
                            )
                        )
                        names.add(tag)

    if len(proxies) == before:
        return config_text
    data["proxies"] = proxies
    _refresh_clash_proxy_groups(data)
    return yaml.dump(data, sort_keys=False, allow_unicode=True)


def _clash_from_uri(uri: str, name: str, ptype: str) -> dict:
    """Minimal URI → mihomo proxy (enough for one-click import)."""
    parsed = parse.urlparse(uri)
    auth = parse.unquote(parsed.username or "")
    if parsed.password:
        auth = f"{auth}:{parse.unquote(parsed.password)}"
    q = dict(parse.parse_qsl(parsed.query))
    node: dict = {
        "name": name,
        "type": ptype,
        "server": parsed.hostname or "",
        "port": parsed.port or 443,
        "udp": True,
    }
    if ptype == "hysteria2":
        node["password"] = parse.unquote(parsed.username or "")
        node["tls"] = True
        if q.get("sni"):
            node["sni"] = q["sni"]
        if q.get("insecure") == "1":
            node["skip-cert-verify"] = True
        if q.get("obfs-password"):
            node["obfs"] = q.get("obfs") or "salamander"
            node["obfs-password"] = q["obfs-password"]
    elif ptype == "tuic":
        parts = (parsed.netloc.split("@")[0] or "").split(":")
        if len(parts) >= 2:
            node["uuid"] = parse.unquote(parts[0])
            node["password"] = parse.unquote(parts[1])
        node["tls"] = True
        if q.get("sni"):
            node["sni"] = q["sni"]
        if q.get("insecure") == "1":
            node["skip-cert-verify"] = True
    elif ptype == "anytls":
        node["password"] = parse.unquote(parsed.username or "")
        node["tls"] = True
        if q.get("sni"):
            node["servername"] = q["sni"]
        if q.get("insecure") == "1":
            node["skip-cert-verify"] = True
    return node


def _append_v2ray_json(user: "UserResponse", config_text: str) -> str:
    from app.db import GetDB, crud
    from app.models.node import NodeStatus

    data = json.loads(config_text)
    if not isinstance(data, list):
        return config_text

    with GetDB() as db:
        nodes = [n for n in crud.get_nodes(db) if n.status == NodeStatus.connected]
        wg_nodes = [n for n in nodes if n.core_kind == "wireguard" or getattr(n, "wireguard", None)]
        exports = _collect_wireguard_exports(user, wg_nodes)
        if not exports:
            return config_text

        wg_outbounds = [
            _xray_wireguard_outbound(
                tag=tag,
                settings=wg_settings,
                wg_node=wg_node,
                host=host,
                port=port,
                local_addr=addr,
                variant=variant,
            )
            for variant, tag, wg_node, wg_settings, host, port, addr in exports
        ]

        for cfg in data:
            if not isinstance(cfg, dict):
                continue
            outbounds = list(cfg.get("outbounds") or [])
            tags = {o.get("tag") for o in outbounds if o.get("tag")}
            for ob in wg_outbounds:
                if ob["tag"] not in tags:
                    outbounds.insert(0, ob)
                    tags.add(ob["tag"])
            cfg["outbounds"] = outbounds

    return json.dumps(data, indent=4)


def merge_unified_subscription(user: "UserResponse", config: str, config_format: str) -> str:
    """Append non-Xray product protocols when the client format supports them."""
    if config_format == "sing-box":
        return _append_singbox(user, config)
    if config_format == "clash-meta":
        return _append_clash_meta(user, config)
    if config_format == "v2ray-json":
        return _append_v2ray_json(user, config)
    return config


def user_has_unified_protocols(user: "UserResponse") -> bool:
    """True when the user has node/sing-box or native WG product proxies."""
    proxies = user.proxies or {}
    return any(
        ptype in proxies
        for ptype in (
            ProxyTypes.Hysteria2,
            ProxyTypes.TUIC,
            ProxyTypes.AnyTLS,
            ProxyTypes.WireGuard,
        )
    )


def collect_unified_share_links(user: "UserResponse") -> list[str]:
    """Share URIs for QUIC/WG protocols (for v2ray base64 subscriptions)."""
    from app.db import GetDB, crud
    from app.models.node import NodeStatus
    from app.subscription.wireguard import user_share_link

    links: list[str] = []
    with GetDB() as db:
        nodes = [n for n in crud.get_nodes(db) if n.status == NodeStatus.connected]
        wg_nodes = [n for n in nodes if n.core_kind == "wireguard" or getattr(n, "wireguard", None)]
        sb_nodes = [n for n in nodes if getattr(n, "singbox", None)]

        settings = _client_settings(user, ProxyTypes.Hysteria2)
        if settings:
            node = pick_node(sb_nodes)
            if node and node.singbox and node.singbox.hysteria2_enabled:
                link = user_hysteria2_link(
                    settings, node, remark=f"{user.username}-{node.name}-hy2",
                    speed_limit_up=user.speed_limit_up,
                    speed_limit_down=user.speed_limit_down,
                )
                if link:
                    links.append(link)

        settings = _client_settings(user, ProxyTypes.TUIC)
        if settings:
            node = pick_node(sb_nodes)
            if node and node.singbox and node.singbox.tuic_enabled:
                link = user_tuic_link(
                    settings, node, remark=f"{user.username}-{node.name}-tuic",
                    speed_limit_up=user.speed_limit_up,
                    speed_limit_down=user.speed_limit_down,
                )
                if link:
                    links.append(link)

        settings = _client_settings(user, ProxyTypes.AnyTLS)
        if settings:
            node = pick_node(sb_nodes)
            if node and node.singbox and node.singbox.anytls_enabled:
                link = user_anytls_link(
                    settings, node, remark=f"{user.username}-{node.name}-anytls",
                    speed_limit_up=user.speed_limit_up,
                    speed_limit_down=user.speed_limit_down,
                )
                if link:
                    links.append(link)

        settings = _client_settings(user, ProxyTypes.WireGuard)
        if settings:
            wg = pick_node(wg_nodes)
            if wg and wg.wireguard:
                for variant in ("plain", "awg"):
                    remark = f"{user.username}-{wg.name}" + ("-awg" if variant == "awg" else "")
                    uri = user_share_link(settings, wg, variant=variant, remark=remark)
                    if uri:
                        links.append(uri)

    return links
