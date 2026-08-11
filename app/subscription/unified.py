"""Merge WireGuard / QUIC product protocols into unified subscriptions."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional
from urllib import parse

import yaml

from app.models.proxy import ProxyTypes
from app.singbox.quality import hysteria2_outbound_quality, tuic_outbound_quality
from app.singbox.speed import speed_tier
from app.subscription.quic import (
    singbox_link_insecure,
    filter_singbox_client_entry_nodes,
    user_anytls_link,
    user_hysteria2_link,
    user_tuic_link,
)
from app.subscription.region_display import node_config_remark
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
    # "plain" and "xray_native" share the node's regular identity keypair —
    # the noise-obfuscated inbound reuses it (see app/wireguard/xray_native.py).
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
    noise: Optional[dict] = None,
    mtu: Optional[int] = None,
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
    if mtu is None:
        if noise is not None:
            from app.wireguard.xray_native import finalmask_client_mtu

            mtu = finalmask_client_mtu(wg_node.wireguard)
        else:
            mtu = wg_node.wireguard.mtu or 1420
    outbound = {
        "tag": tag,
        "protocol": "wireguard",
        "settings": {
            "secretKey": settings.get("private_key"),
            "address": [local_addr] if local_addr else [],
            "mtu": int(mtu),
            "peers": [peer],
        },
    }
    if noise is not None:
        # Xray-core-only wire transform (Finalmask): disguises the WG handshake
        # bytes so DPI can't fingerprint the protocol. Only meaningful when this
        # outbound targets the node's native WG+noise inbound (see
        # app/wireguard/xray_native.py) — stock WireGuard clients never see this
        # path since they can only import the plain .conf/wireguard:// forms.
        outbound["settings"]["noKernelTun"] = True
        outbound["streamSettings"] = {
            "finalmask": {"udp": [{"type": "noise", "settings": noise}]}
        }
    return outbound


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


def _relay_ok_for_client(wg_node, *, db=None) -> bool:
    """False when this node is a tunnel relay whose capture path is not ready.

    Clients should only receive endpoints for stable relays; unhealthy hops are
    omitted so subscriptions auto-prefer working tunnels.

    Pass a shared ``db`` when filtering many nodes so we do not open one session
    (and rebuild the tunnel index) per hop under concurrent import storms.
    """
    try:
        from app import xray
        from app.db import GetDB
        from app.tunnel.relay import (
            node_delegates_wireguard_to_tunnel,
            relay_tunnel_xray_ready,
        )

        nid = int(getattr(wg_node, "id", 0) or 0)
        if not nid:
            return True
        msg = (getattr(wg_node, "message", None) or "").strip().lower()
        if any(
            tok in msg
            for tok in ("xray down", "xray core not running", "degraded", "backoff")
        ):
            # Still allow if live capture probe says ready.
            pass

        def _check(session) -> bool:
            if not node_delegates_wireguard_to_tunnel(session, nid):
                return True
            live = xray.nodes.get(nid)
            # probe=False: rendering a subscription must never open an RPyC
            # session to a node (an unreachable relay would hang the request).
            return bool(
                relay_tunnel_xray_ready(live, db=session, node_id=nid, probe=False)
            )

        if db is not None:
            return _check(db)
        with GetDB() as session:
            return _check(session)
    except Exception:
        return True


def _collect_wireguard_exports(
    user: "UserResponse",
    wg_nodes: list,
    *,
    prefer_xray_native: bool = False,
) -> list[tuple[str, str, object, dict, str, int, str, Optional[dict]]]:
    """Return (variant, tag, wg_node, settings, host, port, local_addr, noise) tuples.

    ``variant`` is one of ``"plain"``, ``"awg"``, or ``"xray_native"``. The
    latter targets a node's Xray-native WG+noise inbound
    (app/wireguard/xray_native.py) and carries a non-``None`` ``noise`` dict —
    only Xray-core outbound consumers (the v2ray-json export) should honour
    it; sing-box/clash-meta have no Finalmask support and must skip it, since
    dialing that port without the matching noise wrapper simply fails.

    When ``prefer_xray_native`` is True (v2ray-json / Xray app imports) and the
    node has Finalmask enabled, plain/awg exports for that node are omitted so
    clients do not try to import stock WireGuard that Xray apps cannot use.
    """
    from app.wireguard.finalmask_shard import finalmask_client_port
    from app.wireguard.xray_native import DEFAULT_NOISE_SETTINGS, xray_native_wg_enabled

    settings = _client_settings(user, ProxyTypes.WireGuard)
    if not (settings and wg_nodes):
        return []
    from app.db import GetDB
    from app.subscription.wireguard import node_host_endpoints

    exports: list[tuple[str, str, object, dict, str, int, str, Optional[dict]]] = []
    with GetDB() as db:
        for wg in wg_nodes:
            if not wg.wireguard:
                continue
            # Skip tunnel relays that are not capture-ready so clients only dial
            # stable hops (healthy Reality path). Exits / non-delegated stay.
            if not _relay_ok_for_client(wg, db=db):
                continue
            native_ok = bool(
                xray_native_wg_enabled(wg.wireguard) and settings.get("private_key")
            )
            # Xray apps import Finalmask JSON, not wireguard:// / plain WG.
            emit_direct = not (prefer_xray_native and native_ok)
            if emit_direct:
                for variant in ("plain", "awg"):
                    try:
                        if not user_config(settings, wg, variant=variant):
                            continue
                        endpoints = node_host_endpoints(wg, variant=variant)
                    except Exception:
                        continue
                    if not endpoints:
                        continue
                    addr = settings.get("awg_address" if variant == "awg" else "address") or ""
                    for i, ep in enumerate(endpoints):
                        host, port_str = ep.rsplit(":", 1)
                        # Strip IPv6 brackets from host for outbound JSON fields.
                        host_clean = host[1:-1] if host.startswith("[") and host.endswith("]") else host
                        proto = "AmneziaWG" if variant == "awg" else "WireGuard"
                        tag = node_config_remark(
                            wg, proto, host_index=i, include_node_name=True,
                        )
                        exports.append((variant, tag, wg, settings, host_clean, int(port_str), addr, None))
            if native_ok:
                # Prefer Hosts / plain endpoint host; dial the user's sticky shard port.
                # Always emit even when plain/awg .conf can't be built so Finalmask
                # reaches the v2ray-json subscription.
                try:
                    plain_eps = node_host_endpoints(wg, variant="plain")
                except Exception:
                    plain_eps = []
                shard_port = finalmask_client_port(wg.wireguard, settings)
                if not plain_eps:
                    try:
                        plain_eps = [node_endpoint(wg, variant="plain")]
                    except Exception:
                        plain_eps = [f"{wg.address}:{shard_port}"]
                host = plain_eps[0].rsplit(":", 1)[0]
                host_clean = host[1:-1] if host.startswith("[") and host.endswith("]") else host
                addr = settings.get("address") or settings.get("awg_address") or ""
                if addr:
                    exports.append((
                        "xray_native",
                        node_config_remark(wg, "WireGuard", include_node_name=True),
                        wg,
                        settings,
                        host_clean,
                        shard_port,
                        addr,
                        wg.wireguard.xray_wg_noise or DEFAULT_NOISE_SETTINGS,
                    ))
                elif prefer_xray_native and emit_direct is False:
                    # Finalmask preferred but no client address yet — nothing to emit.
                    pass
    return exports


def _singbox_tls(dbnode, host: str, *, sni: str | None = None) -> dict:
    cfg = dbnode.singbox
    insecure = singbox_link_insecure(cfg)
    tls: dict = {"enabled": True, "server_name": sni or host}
    if insecure:
        tls["insecure"] = True
    return tls


def _singbox_client_dial(dbnode, preferred_host: str) -> tuple[str, str]:
    """Dial host/SNI for client sing-box JSON (same policy as share URIs)."""
    from app.subscription.quic import singbox_dial_host_sni

    return singbox_dial_host_sni(dbnode, dbnode.singbox, preferred_host)


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
        sb_nodes = filter_singbox_client_entry_nodes(
            db, [n for n in nodes if getattr(n, "singbox", None)]
        )

        # WireGuard → sing-box wireguard outbound (one outbound per connected node)
        if ProxyTypes.WireGuard in (user.proxies or {}):
            settings = _client_settings(user, ProxyTypes.WireGuard)
            for variant, tag, wg, wg_settings, host, port, addr, _noise in _collect_wireguard_exports(
                user, wg_nodes
            ):
                if tag in tags or variant == "xray_native":
                    # Finalmask noise is an Xray-core-only wire transform;
                    # sing-box has no client for it, so it must never dial
                    # this port with a plain WireGuard handshake.
                    continue
                outbounds.append({
                    "type": "wireguard",
                    "tag": tag,
                    "server": host,
                    "server_port": port,
                    "local_address": [addr] if addr else [],
                    "private_key": wg_settings.get("private_key"),
                    "peer_public_key": (
                        wg.wireguard.awg_public_key if variant == "awg"
                        else wg.wireguard.public_key
                    ),
                    "mtu": wg.wireguard.mtu or 1280,
                })
                if wg_settings.get("preshared_key"):
                    outbounds[-1]["pre_shared_key"] = wg_settings["preshared_key"]
                tags.add(tag)

        from app.subscription.host_buckets import singbox_dial_endpoints

        settings = _client_settings(user, ProxyTypes.Hysteria2)
        if settings:
            for node in sb_nodes:
                if not (node.singbox and node.singbox.hysteria2_enabled):
                    continue
                from app.singbox.sync import hysteria2_port_for_user

                hy2_port = hysteria2_port_for_user(
                    int(node.singbox.hysteria2_port),
                    user.speed_limit_up,
                    user.speed_limit_down,
                )
                tier_limited = speed_tier(user.speed_limit_up, user.speed_limit_down) is not None
                dials = singbox_dial_endpoints(
                    node,
                    "__native:hysteria2",
                    default_host=node.singbox.sni or node.address,
                    default_port=hy2_port,
                )
                for i, (host, port) in enumerate(dials):
                    tag = node_config_remark(
                        node, "Hysteria2", host_index=i, include_node_name=True,
                    )
                    if tag in tags:
                        continue
                    dial_host, dial_sni = _singbox_client_dial(node, host)
                    outbounds.append({
                        "type": "hysteria2",
                        "tag": tag,
                        "server": dial_host,
                        "server_port": port,
                        "password": settings.get("password"),
                        "tls": _singbox_tls(node, dial_host, sni=dial_sni),
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
            for node in sb_nodes:
                if not (node.singbox and node.singbox.tuic_enabled):
                    continue
                from app.singbox.sync import tuic_port_for_user

                tuic_port = tuic_port_for_user(
                    int(node.singbox.tuic_port),
                    user.speed_limit_up,
                    user.speed_limit_down,
                )
                dials = singbox_dial_endpoints(
                    node,
                    "__native:tuic",
                    default_host=node.singbox.sni or node.address,
                    default_port=tuic_port,
                )
                for i, (host, port) in enumerate(dials):
                    tag = node_config_remark(
                        node, "TUIC", host_index=i, include_node_name=True,
                    )
                    if tag in tags:
                        continue
                    dial_host, dial_sni = _singbox_client_dial(node, host)
                    outbounds.append({
                        "type": "tuic",
                        "tag": tag,
                        "server": dial_host,
                        "server_port": port,
                        "uuid": str(settings.get("uuid") or ""),
                        "password": settings.get("password"),
                        "tls": _singbox_tls(node, dial_host, sni=dial_sni),
                        **tuic_outbound_quality(
                            congestion_control=node.singbox.tuic_congestion_control or "bbr"
                        ),
                    })
                    tags.add(tag)

        settings = _client_settings(user, ProxyTypes.AnyTLS)
        if settings:
            for node in sb_nodes:
                if not (node.singbox and node.singbox.anytls_enabled):
                    continue
                host = node.singbox.sni or node.address
                tag = node_config_remark(node, "AnyTLS", include_node_name=True)
                if tag in tags:
                    continue
                from app.singbox.sync import anytls_port_for_user

                anytls_port = anytls_port_for_user(
                    int(node.singbox.anytls_port),
                    user.speed_limit_up,
                    user.speed_limit_down,
                )
                dial_host, dial_sni = _singbox_client_dial(node, host)
                outbounds.append({
                    "type": "anytls",
                    "tag": tag,
                    "server": dial_host,
                    "server_port": anytls_port,
                    "password": settings.get("password"),
                    "tls": _singbox_tls(node, dial_host, sni=dial_sni),
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
        sb_nodes = filter_singbox_client_entry_nodes(
            db, [n for n in nodes if getattr(n, "singbox", None)]
        )
        wg_nodes = [n for n in nodes if n.core_kind == "wireguard" or getattr(n, "wireguard", None)]

        from app.subscription.host_buckets import singbox_dial_endpoints
        from app.singbox.sync import hysteria2_port_for_user, tuic_port_for_user

        settings = _client_settings(user, ProxyTypes.Hysteria2)
        if settings:
            for node in sb_nodes:
                if not (node.singbox and node.singbox.hysteria2_enabled):
                    continue
                hy2_port = hysteria2_port_for_user(
                    int(node.singbox.hysteria2_port),
                    user.speed_limit_up,
                    user.speed_limit_down,
                )
                dials = singbox_dial_endpoints(
                    node,
                    "__native:hysteria2",
                    default_host=node.singbox.sni or node.address,
                    default_port=hy2_port,
                )
                for i, (host, port) in enumerate(dials):
                    tag = node_config_remark(
                        node, "Hysteria2", host_index=i, include_node_name=True,
                    )
                    link = user_hysteria2_link(
                        settings, node, remark=tag,
                        speed_limit_up=user.speed_limit_up,
                        speed_limit_down=user.speed_limit_down,
                        host=host,
                        port=port,
                    )
                    if link and tag not in names:
                        proxies.append(_clash_from_uri(link, tag, "hysteria2"))
                        names.add(tag)

        settings = _client_settings(user, ProxyTypes.TUIC)
        if settings:
            for node in sb_nodes:
                if not (node.singbox and node.singbox.tuic_enabled):
                    continue
                tuic_port = tuic_port_for_user(
                    int(node.singbox.tuic_port),
                    user.speed_limit_up,
                    user.speed_limit_down,
                )
                dials = singbox_dial_endpoints(
                    node,
                    "__native:tuic",
                    default_host=node.singbox.sni or node.address,
                    default_port=tuic_port,
                )
                for i, (host, port) in enumerate(dials):
                    tag = node_config_remark(
                        node, "TUIC", host_index=i, include_node_name=True,
                    )
                    link = user_tuic_link(
                        settings, node, remark=tag,
                        speed_limit_up=user.speed_limit_up,
                        speed_limit_down=user.speed_limit_down,
                        host=host,
                        port=port,
                    )
                    if link and tag not in names:
                        proxies.append(_clash_from_uri(link, tag, "tuic"))
                        names.add(tag)

        settings = _client_settings(user, ProxyTypes.AnyTLS)
        if settings:
            for node in sb_nodes:
                if not (node.singbox and node.singbox.anytls_enabled):
                    continue
                tag = node_config_remark(node, "AnyTLS", include_node_name=True)
                link = user_anytls_link(
                    settings, node, remark=tag,
                    speed_limit_up=user.speed_limit_up,
                    speed_limit_down=user.speed_limit_down,
                )
                if link and tag not in names:
                    proxies.append(_clash_from_uri(link, tag, "anytls"))
                    names.add(tag)

        settings = _client_settings(user, ProxyTypes.WireGuard)
        if settings:
            for variant, tag, wg_node, wg_settings, host, port, addr, _noise in _collect_wireguard_exports(
                user, wg_nodes
            ):
                if variant == "xray_native":
                    # Finalmask is Xray-core-only; clash-meta's wireguard proxy
                    # type cannot speak it.
                    continue
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
        from app.wireguard.xray_native import finalmask_client_mtu

        nodes = [n for n in crud.get_nodes(db) if n.status == NodeStatus.connected]
        wg_nodes = [n for n in nodes if n.core_kind == "wireguard" or getattr(n, "wireguard", None)]
        exports = _collect_wireguard_exports(user, wg_nodes, prefer_xray_native=True)
        if not exports:
            return config_text

        wg_outbounds = []
        for variant, tag, wg_node, wg_settings, host, port, addr, noise in exports:
            mtu = None
            if variant == "xray_native" and wg_node.wireguard:
                mtu = finalmask_client_mtu(wg_node.wireguard, dbnode=wg_node, db=db)
            wg_outbounds.append(
                _xray_wireguard_outbound(
                    tag=tag,
                    settings=wg_settings,
                    wg_node=wg_node,
                    host=host,
                    port=port,
                    local_addr=addr,
                    variant=variant,
                    noise=noise,
                    mtu=mtu,
                )
            )

        # Standalone profiles (once each). Cloning into every VLESS config made
        # Xray apps show N identical WireGuard entries.
        existing_remarks = {
            str(cfg.get("remarks") or "")
            for cfg in data
            if isinstance(cfg, dict)
        }
        base = next((cfg for cfg in data if isinstance(cfg, dict)), None)
        for ob in wg_outbounds:
            remark = str(ob.get("tag") or "WireGuard")
            if remark in existing_remarks:
                continue
            if base is not None:
                profile = json.loads(json.dumps(base))
            else:
                profile = {"log": {"loglevel": "warning"}, "routing": {"domainStrategy": "AsIs", "rules": []}}
            profile["remarks"] = remark
            # Keep template freedom/blackhole after the WG outbound (selected first).
            rest = [
                o
                for o in (profile.get("outbounds") or [])
                if isinstance(o, dict)
                and str(o.get("protocol") or "") in ("freedom", "blackhole", "dns")
            ]
            profile["outbounds"] = [ob, *rest]
            data.append(profile)
            existing_remarks.add(remark)

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


def collect_unified_share_links(
    user: "UserResponse",
    *,
    exclude_protocols: Optional[set[str]] = None,
) -> list[str]:
    """Share URIs for QUIC/WG protocols (for v2ray base64 subscriptions).

    ``exclude_protocols`` uses lowercase scheme names (``hysteria2``, ``tuic``,
    ``anytls``, ``wireguard``) for clients that cannot handle them reliably.
    """
    from app.db import GetDB, crud
    from app.models.node import NodeStatus
    from app.subscription.wireguard import user_share_link

    skip = {p.lower() for p in (exclude_protocols or set())}
    links: list[str] = []
    with GetDB() as db:
        nodes = [n for n in crud.get_nodes(db) if n.status == NodeStatus.connected]
        wg_nodes = [n for n in nodes if n.core_kind == "wireguard" or getattr(n, "wireguard", None)]
        sb_nodes = filter_singbox_client_entry_nodes(
            db, [n for n in nodes if getattr(n, "singbox", None)]
        )

        settings = _client_settings(user, ProxyTypes.Hysteria2)
        if settings and "hysteria2" not in skip:
            for node in sb_nodes:
                if not (node.singbox and node.singbox.hysteria2_enabled):
                    continue
                link = user_hysteria2_link(
                    settings, node, remark=node_config_remark(node, "Hysteria2"),
                    speed_limit_up=user.speed_limit_up,
                    speed_limit_down=user.speed_limit_down,
                )
                if link:
                    links.append(link)

        settings = _client_settings(user, ProxyTypes.TUIC)
        if settings and "tuic" not in skip:
            for node in sb_nodes:
                if not (node.singbox and node.singbox.tuic_enabled):
                    continue
                link = user_tuic_link(
                    settings, node, remark=node_config_remark(node, "TUIC"),
                    speed_limit_up=user.speed_limit_up,
                    speed_limit_down=user.speed_limit_down,
                )
                if link:
                    links.append(link)

        settings = _client_settings(user, ProxyTypes.AnyTLS)
        if settings and "anytls" not in skip:
            for node in sb_nodes:
                if not (node.singbox and node.singbox.anytls_enabled):
                    continue
                link = user_anytls_link(
                    settings, node, remark=node_config_remark(node, "AnyTLS"),
                    speed_limit_up=user.speed_limit_up,
                    speed_limit_down=user.speed_limit_down,
                )
                if link:
                    links.append(link)

        settings = _client_settings(user, ProxyTypes.WireGuard)
        if settings and "wireguard" not in skip:
            from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled
            from app.wireguard.xray_native import xray_native_wg_enabled

            for wg in wg_nodes:
                if not wg.wireguard:
                    continue
                # Finalmask-only for Xray share-link / base64 subs (with fm=).
                # Stock WireGuard .conf (no fm) stays on GET /sub/.../wireguard —
                # emitting both URIs made apps import two identical WireGuards.
                if xray_native_wg_enabled(wg.wireguard):
                    uri = user_share_link(
                        settings, wg, variant="xray_native",
                        remark=node_config_remark(wg, "WireGuard"), db=db,
                    )
                    if uri:
                        links.append(uri)
                elif plain_wg_enabled(wg.wireguard):
                    uri = user_share_link(
                        settings, wg, variant="plain",
                        remark=node_config_remark(wg, "WireGuard"), db=db,
                    )
                    if uri:
                        links.append(uri)
                if amneziawg_enabled(wg.wireguard):
                    uri = user_share_link(
                        settings, wg, variant="awg",
                        remark=node_config_remark(wg, "AmneziaWG"), db=db,
                    )
                    if uri:
                        links.append(uri)

    return links
