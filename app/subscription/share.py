import base64
import random
from collections import defaultdict
from datetime import datetime as dt
from datetime import timedelta
from typing import TYPE_CHECKING, List, Literal, Union

from jdatetime import date as jd

from app import xray
from app.models.proxy import ProxyTypes
from app.xray.network_defaults import default_tls_fingerprint
from app.utils.system import get_public_ip, get_public_ipv6, readable_size

from . import *

if TYPE_CHECKING:
    from app.models.user import UserResponse

from config import (
    ACTIVE_STATUS_TEXT,
    DISABLED_STATUS_TEXT,
    EXPIRED_STATUS_TEXT,
    LIMITED_STATUS_TEXT,
    ONHOLD_STATUS_TEXT,
)

SERVER_IP = get_public_ip()
SERVER_IPV6 = get_public_ipv6()

STATUS_EMOJIS = {
    "active": "✅",
    "expired": "⌛️",
    "limited": "🪫",
    "disabled": "❌",
    "on_hold": "🔌",
}

STATUS_TEXTS = {
    "active": ACTIVE_STATUS_TEXT,
    "expired": EXPIRED_STATUS_TEXT,
    "limited": LIMITED_STATUS_TEXT,
    "disabled": DISABLED_STATUS_TEXT,
    "on_hold": ONHOLD_STATUS_TEXT,
}


def generate_v2ray_links(proxies: dict, inbounds: dict, extra_data: dict, reverse: bool) -> list:
    format_variables = setup_format_variables(extra_data)
    conf = V2rayShareLink()
    return process_inbounds_and_tags(inbounds, proxies, format_variables, conf=conf, reverse=reverse)


def generate_clash_subscription(
        proxies: dict, inbounds: dict, extra_data: dict, reverse: bool, is_meta: bool = False
) -> str:
    if is_meta is True:
        conf = ClashMetaConfiguration()
    else:
        conf = ClashConfiguration()

    format_variables = setup_format_variables(extra_data)
    return process_inbounds_and_tags(
        inbounds, proxies, format_variables, conf=conf, reverse=reverse
    )


def generate_singbox_subscription(
        proxies: dict, inbounds: dict, extra_data: dict, reverse: bool
) -> str:
    conf = SingBoxConfiguration()

    format_variables = setup_format_variables(extra_data)
    return process_inbounds_and_tags(
        inbounds, proxies, format_variables, conf=conf, reverse=reverse
    )


def generate_outline_subscription(
        proxies: dict, inbounds: dict, extra_data: dict, reverse: bool,
) -> str:
    conf = OutlineConfiguration()

    format_variables = setup_format_variables(extra_data)
    return process_inbounds_and_tags(
        inbounds, proxies, format_variables, conf=conf, reverse=reverse
    )


def generate_v2ray_json_subscription(
        proxies: dict, inbounds: dict, extra_data: dict, reverse: bool,
) -> str:
    conf = V2rayJsonConfig()

    format_variables = setup_format_variables(extra_data)
    return process_inbounds_and_tags(
        inbounds, proxies, format_variables, conf=conf, reverse=reverse
    )


def generate_surge_subscription(
        proxies: dict, inbounds: dict, extra_data: dict, reverse: bool,
) -> str:
    from app.subscription.surge import SurgeConfiguration

    conf = SurgeConfiguration()
    format_variables = setup_format_variables(extra_data)
    return process_inbounds_and_tags(
        inbounds, proxies, format_variables, conf=conf, reverse=reverse
    )


def generate_loon_subscription(
        proxies: dict, inbounds: dict, extra_data: dict, reverse: bool,
) -> str:
    from app.subscription.loon import LoonConfiguration

    conf = LoonConfiguration()
    format_variables = setup_format_variables(extra_data)
    return process_inbounds_and_tags(
        inbounds, proxies, format_variables, conf=conf, reverse=reverse
    )


def generate_quantumult_subscription(
        proxies: dict, inbounds: dict, extra_data: dict, reverse: bool,
) -> str:
    from app.subscription.quantumult import QuantumultConfiguration

    conf = QuantumultConfiguration()
    format_variables = setup_format_variables(extra_data)
    return process_inbounds_and_tags(
        inbounds, proxies, format_variables, conf=conf, reverse=reverse
    )


def _filter_inbounds_by_tag(inbounds: dict, inbound_tag: str | None) -> dict:
    if not inbound_tag:
        return inbounds
    filtered: dict = {}
    for protocol, tags in (inbounds or {}).items():
        kept = [t for t in tags if t == inbound_tag]
        if kept:
            filtered[protocol] = kept
    return filtered


def _supplementary_inbounds(inbounds: dict, inbound_filter: str | None) -> dict:
    """Xray inbounds assigned to the user but outside ``inbound_filter``.

    Per-inbound subscription endpoints (``export_mode=inbound_only``) scope the
    primary link to one inbound tag, but QUIC/WG product protocols were already
    included via :func:`collect_unified_share_links`. Other Xray protocols the
    user was explicitly given (e.g. Shadowsocks on a separate inbound) must
    appear in the same subscription body too — otherwise the subscribe page
    (which lists all ``links``) disagrees with what clients import.
    """
    if not inbound_filter:
        return {}
    primary = _filter_inbounds_by_tag(inbounds, inbound_filter)
    supplementary: dict = {}
    for protocol, tags in (inbounds or {}).items():
        kept = [t for t in tags if t not in (primary.get(protocol) or [])]
        if kept:
            supplementary[protocol] = kept
    return supplementary


def collect_xray_share_links(
    user: "UserResponse",
    *,
    inbound_filter: str | None = None,
    reverse: bool = False,
) -> list[str]:
    """Xray-compatible share URIs only (vless/vmess/trojan/ss) for v2ray clients."""
    primary = _filter_inbounds_by_tag(user.inbounds, inbound_filter)
    extra = _supplementary_inbounds(user.inbounds, inbound_filter)
    links: list[str] = []
    extra_data = user.model_dump()
    if primary:
        links.extend(
            generate_v2ray_links(user.proxies, primary, extra_data, reverse=reverse)
        )
    if extra:
        links.extend(
            generate_v2ray_links(user.proxies, extra, extra_data, reverse=reverse)
        )
    return links


def collect_v2ray_share_links(
    user: "UserResponse",
    *,
    inbound_filter: str | None = None,
    reverse: bool = False,
) -> list[str]:
    """All share URIs including QUIC/WG (for display endpoints that tolerate mixed schemes)."""
    links = collect_xray_share_links(
        user, inbound_filter=inbound_filter, reverse=reverse
    )
    from app.subscription.unified import collect_unified_share_links

    links.extend(collect_unified_share_links(user))
    return links


def collect_v2ray_share_link_items(
    user: "UserResponse",
    *,
    inbound_filter: str | None = None,
    reverse: bool = False,
) -> list[dict]:
    """Structured metadata for each Xray share link (flags, remark, protocol)."""
    inbounds = _filter_inbounds_by_tag(user.inbounds, inbound_filter)
    format_variables = setup_format_variables(user.__dict__)
    conf = V2rayShareLink()
    process_inbounds_and_tags(
        inbounds, user.proxies, format_variables, conf=conf, reverse=reverse
    )
    items = list(conf.link_items)
    from app.subscription.region_display import parse_link_remark, split_remark_flag
    from app.subscription.unified import collect_unified_share_links

    for raw in collect_unified_share_links(user):
        remark = parse_link_remark(raw)
        flag, title = split_remark_flag(remark)
        proto = raw.split("://", 1)[0] if "://" in raw else "link"
        items.append(
            {
                "link": raw,
                "protocol": proto,
                "remark": title or remark,
                "region_flag": flag,
                "region_name": title or remark,
                "address_hint": "",
            }
        )
    return items


def link_items_from_urls(links: list[str]) -> list[dict]:
    from app.subscription.region_display import parse_link_remark, split_remark_flag

    items: list[dict] = []
    for raw in links:
        remark = parse_link_remark(raw)
        flag, title = split_remark_flag(remark)
        proto = raw.split("://", 1)[0] if "://" in raw else "link"
        items.append(
            {
                "link": raw,
                "protocol": proto,
                "remark": title or remark,
                "region_flag": flag,
                "region_name": title or remark,
                "address_hint": "",
            }
        )
    return items


def generate_subscription(
        user: "UserResponse",
        config_format: Literal["v2ray", "clash-meta", "clash", "sing-box", "outline", "v2ray-json", "surge", "loon", "quantumult"],
        as_base64: bool,
        reverse: bool,
        inbound_filter: str | None = None,
) -> str:
    inbounds = _filter_inbounds_by_tag(user.inbounds, inbound_filter)
    kwargs = {
        "proxies": user.proxies,
        "inbounds": inbounds,
        "extra_data": user.__dict__,
        "reverse": reverse,
    }

    if config_format == "v2ray":
        links = collect_v2ray_share_links(
            user, inbound_filter=inbound_filter, reverse=reverse
        )
        config = "\n".join(links)
    elif config_format == "clash-meta":
        config = generate_clash_subscription(**kwargs, is_meta=True)
    elif config_format == "clash":
        config = generate_clash_subscription(**kwargs)
    elif config_format == "sing-box":
        config = generate_singbox_subscription(**kwargs)
    elif config_format == "outline":
        config = generate_outline_subscription(**kwargs)
    elif config_format == "v2ray-json":
        config = generate_v2ray_json_subscription(**kwargs)
    elif config_format == "surge":
        config = generate_surge_subscription(**kwargs)
    elif config_format == "loon":
        config = generate_loon_subscription(**kwargs)
    elif config_format == "quantumult":
        config = generate_quantumult_subscription(**kwargs)
    else:
        raise ValueError(f'Unsupported format "{config_format}"')

    from app.routing_presets import (
        apply_dns_policy_to_clash,
        apply_dns_policy_to_json,
        apply_dns_policy_to_singbox,
        apply_routing_preset_to_json,
    )

    preset = kwargs["extra_data"].get("routing_preset")
    dns_policy = kwargs["extra_data"].get("dns_policy")
    if config_format == "v2ray-json" and (preset or dns_policy):
        if preset:
            config = apply_routing_preset_to_json(config, preset)
        if dns_policy:
            config = apply_dns_policy_to_json(config, dns_policy)
    elif config_format == "sing-box" and dns_policy:
        config = apply_dns_policy_to_singbox(config, dns_policy)
    elif config_format in ("clash-meta", "clash") and dns_policy:
        config = apply_dns_policy_to_clash(config, dns_policy)

    from app.subscription.unified import merge_unified_subscription

    if config_format in ("clash-meta", "sing-box", "v2ray-json"):
        config = merge_unified_subscription(user, config, config_format)

    if as_base64:
        config = base64.b64encode(config.encode()).decode()

    return config


def format_time_left(seconds_left: int) -> str:
    if not seconds_left or seconds_left <= 0:
        return "∞"

    minutes, seconds = divmod(seconds_left, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    months, days = divmod(days, 30)

    result = []
    if months:
        result.append(f"{months}m")
    if days:
        result.append(f"{days}d")
    if hours and (days < 7):
        result.append(f"{hours}h")
    if minutes and not (months or days):
        result.append(f"{minutes}m")
    if seconds and not (months or days):
        result.append(f"{seconds}s")
    return " ".join(result)


def setup_format_variables(extra_data: dict) -> dict:
    from app.models.user import UserStatus

    user_status = extra_data.get("status")
    expire_timestamp = extra_data.get("expire")
    on_hold_expire_duration = extra_data.get("on_hold_expire_duration")
    now = dt.utcnow()
    now_ts = now.timestamp()

    if user_status != UserStatus.on_hold:
        if expire_timestamp is not None and expire_timestamp >= 0:
            seconds_left = expire_timestamp - int(dt.utcnow().timestamp())
            expire_datetime = dt.fromtimestamp(expire_timestamp)
            expire_date = expire_datetime.date()
            jalali_expire_date = jd.fromgregorian(
                year=expire_date.year, month=expire_date.month, day=expire_date.day
            ).strftime("%Y-%m-%d")
            if now_ts < expire_timestamp:
                days_left = (expire_datetime - dt.utcnow()).days + 1
                time_left = format_time_left(seconds_left)
            else:
                days_left = "0"
                time_left = "0"

        else:
            days_left = "∞"
            time_left = "∞"
            expire_date = "∞"
            jalali_expire_date = "∞"
    else:
        if on_hold_expire_duration is not None and on_hold_expire_duration >= 0:
            days_left = timedelta(seconds=on_hold_expire_duration).days
            time_left = format_time_left(on_hold_expire_duration)
            expire_date = "-"
            jalali_expire_date = "-"
        else:
            days_left = "∞"
            time_left = "∞"
            expire_date = "∞"
            jalali_expire_date = "∞"

    if extra_data.get("data_limit"):
        data_limit = readable_size(extra_data["data_limit"])
        data_left = extra_data["data_limit"] - extra_data["used_traffic"]
        if data_left < 0:
            data_left = 0
        data_left = readable_size(data_left)
    else:
        data_limit = "∞"
        data_left = "∞"

    status_emoji = STATUS_EMOJIS.get(extra_data.get("status")) or ""
    status_text = STATUS_TEXTS.get(extra_data.get("status")) or ""

    format_variables = defaultdict(
        lambda: "<missing>",
        {
            "SERVER_IP": SERVER_IP,
            "SERVER_IPV6": SERVER_IPV6,
            "USERNAME": extra_data.get("username", "{USERNAME}"),
            "SPEED_LIMIT_UP": extra_data.get("speed_limit_up"),
            "SPEED_LIMIT_DOWN": extra_data.get("speed_limit_down"),
            "DATA_USAGE": readable_size(extra_data.get("used_traffic")),
            "DATA_LIMIT": data_limit,
            "DATA_LEFT": data_left,
            "DAYS_LEFT": days_left,
            "EXPIRE_DATE": expire_date,
            "JALALI_EXPIRE_DATE": jalali_expire_date,
            "TIME_LEFT": time_left,
            "STATUS_EMOJI": status_emoji,
            "STATUS_TEXT": status_text,
        },
    )
    from app.subscription.region_display import panel_region_vars

    format_variables.update(panel_region_vars())
    return format_variables


from app.subscription.tls_client import _sni_candidates


def _is_template_host(host: dict) -> bool:
    remark = str(host.get("remark") or "")
    addresses = host.get("address") or []
    if isinstance(addresses, str):
        addresses = [addresses]
    addr_text = " ".join(str(a) for a in addresses)
    return "{SERVER_IP}" in addr_text or "{USERNAME}" in remark


def _export_hosts(tag: str, hosts: list[dict], node_id: int | None = None) -> list[dict]:
    from app.utils.node_ids import host_visible_on_node

    active = [
        h
        for h in hosts
        if not h.get("is_disabled") and host_visible_on_node(h.get("node_ids"), node_id)
    ]
    if len(active) <= 1:
        return active
    custom = [h for h in active if not _is_template_host(h)]
    return custom if custom else active


def _expand_host_addresses(
    address_list: list,
    *,
    panel_ip: str,
    node_address: str | None = None,
) -> list:
    out: list = []
    for raw in address_list:
        s = str(raw)
        if node_address is not None:
            s = s.replace("{NODE_IP}", node_address)
        s = s.replace("{SERVER_IP}", panel_ip)
        out.append(s)
    return out


def _multinode_variants(
    address_list: list, format_variables: dict, node_ids_raw: str | None = None
) -> list[tuple[list, str, int | None]]:
    """Fan-out hosts across nodes (template vars or explicit node_ids binding)."""
    from app.utils.node_ids import host_visible_on_node, parse_node_ids

    if not address_list:
        return [(address_list, "", None)]
    joined = " ".join(str(a) for a in address_list)
    from app import xray

    panel_ip = str(format_variables.get("SERVER_IP") or SERVER_IP or "")
    bound_ids = parse_node_ids(node_ids_raw) if node_ids_raw else []
    has_node_ip = "{NODE_IP}" in joined
    has_server_ip = "{SERVER_IP}" in joined
    has_template = has_node_ip or has_server_ip

    # Panel-local inbounds (e.g. Shadowsocks): {SERVER_IP} must stay the panel IP.
    if has_server_ip and not has_node_ip and not bound_ids:
        return [(_expand_host_addresses(address_list, panel_ip=panel_ip), "", None)]

    if not has_template and len(bound_ids) <= 1:
        return [(address_list, "", bound_ids[0] if len(bound_ids) == 1 else None)]

    nodes = [
        n
        for n in xray.nodes.values()
        if getattr(n, "connected", False)
        and getattr(n, "address", None)
        and host_visible_on_node(node_ids_raw, getattr(n, "id", None))
    ]
    if bound_ids and not has_template:
        nodes = [n for n in nodes if getattr(n, "id", None) in bound_ids]
    if len(nodes) <= 1:
        if has_template and nodes:
            node = nodes[0]
            addrs = _expand_host_addresses(
                address_list, panel_ip=panel_ip, node_address=node.address
            )
            return [(addrs, "", getattr(node, "id", None))]
        if has_template:
            return [(_expand_host_addresses(address_list, panel_ip=panel_ip), "", None)]
        return [(address_list, "", bound_ids[0] if len(bound_ids) == 1 else None)]
    out: list[tuple[list, str, int | None]] = []
    for node in nodes:
        name = getattr(node, "name", None) or f"node-{getattr(node, 'id', '?')}"
        nid = getattr(node, "id", None)
        addrs = _expand_host_addresses(
            address_list, panel_ip=panel_ip, node_address=node.address
        )
        out.append((addrs, "", nid))
    return out


def process_inbounds_and_tags(
        inbounds: dict,
        proxies: dict,
        format_variables: dict,
        conf: Union[
            V2rayShareLink,
            V2rayJsonConfig,
            SingBoxConfiguration,
            ClashConfiguration,
            ClashMetaConfiguration,
            OutlineConfiguration,
            "SurgeConfiguration",
            "LoonConfiguration",
            "QuantumultConfiguration",
        ],
        reverse=False,
) -> Union[List, str]:
    from app.subscription.host_export import (
        apply_external_hop_to_host,
        apply_vless_route,
        conf_export_format,
        expand_host_export_variants,
        host_excluded,
        host_tls_extras,
        marshal_final_mask,
        parse_json_object,
        parse_mux_params,
        resolve_host_sni,
    )
    from app.xray import refresh_for_subscription

    refresh_for_subscription()
    export_format = conf_export_format(conf)

    # Deterministic per-user selection: a subscription refresh must resolve to
    # the SAME SNI / host / address / wildcard subdomain for a given user so
    # long-lived client configs keep working, while still distributing users
    # across multi-value host lists. Seed a local RNG from the username instead
    # of using process-global randomness.
    _user_seed = str(format_variables.get("USERNAME") or "")
    rng = random.Random(_user_seed)

    def _stable_salt() -> str:
        return rng.getrandbits(64).to_bytes(8, "big").hex()

    _inbounds = []
    for protocol, tags in inbounds.items():
        for tag in tags:
            _inbounds.append((protocol, [tag]))
    index_dict = {proxy: index for index, proxy in enumerate(
        xray.config.inbounds_by_tag.keys())}
    inbounds = sorted(
        _inbounds, key=lambda x: index_dict.get(x[1][0], float('inf')))

    for protocol, tags in inbounds:
        settings = proxies.get(protocol)
        if not settings:
            continue

        format_variables.update({"PROTOCOL": protocol.name})
        for tag in tags:
            inbound = xray.config.inbounds_by_tag.get(tag)
            if not inbound:
                continue

            from app.xray.inbound_match import inbound_matches_proxy

            if not inbound_matches_proxy(protocol, tag, settings, inbound_meta=inbound):
                continue

            format_variables.update({"TRANSPORT": inbound["network"]})
            for host in _export_hosts(tag, xray.hosts.get(tag, []), node_id=None):
                for hop in expand_host_export_variants(host):
                    export_host = (
                        apply_external_hop_to_host(host, hop) if hop is not None else host
                    )
                    if host_excluded(export_host, export_format):
                        continue

                    host_inbound = inbound.copy()

                    host_sni_override = ""
                    sni_list = export_host["sni"] or []
                    if sni_list:
                        salt = _stable_salt()
                        host_sni_override = str(rng.choice(sni_list)).replace("*", salt)

                    if sids := host_inbound.get("sids") or inbound.get("sids"):
                        host_inbound["sid"] = next(
                            (s for s in sids if s), sids[0] if sids else ""
                        )

                    for address_list, remark_suffix, _node_id in _multinode_variants(
                        export_host["address"] or [],
                        format_variables,
                        export_host.get("node_ids"),
                    ):
                        from app.subscription.region_display import region_vars_for_node, connect_format_vars

                        local_vars = defaultdict(format_variables.default_factory, format_variables)
                        local_vars.update(region_vars_for_node(_node_id))
                        host_region = str(export_host.get("region") or "").strip()
                        if host_region:
                            from app.subscription.region_display import region_format_vars

                            local_vars.update(region_format_vars(host_region))
                        req_host = ""
                        req_host_list = export_host["host"] or inbound["host"]
                        if req_host_list:
                            salt = _stable_salt()
                            req_host = str(rng.choice(req_host_list)).replace("*", salt)

                        address = ""
                        if address_list:
                            salt = _stable_salt()
                            address = rng.choice(address_list).replace('*', salt)

                        connect_vars = connect_format_vars(local_vars)

                        if export_host["path"] is not None:
                            path = export_host["path"].format_map(connect_vars)
                        else:
                            path = inbound.get("path", "").format_map(connect_vars)

                        if export_host.get("use_sni_as_host", False) and host_sni_override:
                            req_host = host_sni_override

                        client_port = export_host["port"] or inbound["port"]
                        if protocol == ProxyTypes.Shadowsocks:
                            up = format_variables.get("SPEED_LIMIT_UP")
                            down = format_variables.get("SPEED_LIMIT_DOWN")
                            if up or down:
                                from app.xray.speed import ss_port_for_user

                                client_port = ss_port_for_user(
                                    int(inbound["port"]),
                                    up,
                                    down,
                                )

                        from app.subscription.tls_client import resolve_subscription_tls

                        tls_client = resolve_subscription_tls(
                            inbound_meta=host_inbound,
                            host_address=address.format_map(connect_vars).strip() if address else "",
                            host_port=client_port,
                            inbound_port=inbound["port"],
                            host_sni_override=host_sni_override,
                            host_tls=export_host["tls"],
                        )
                        resolved_addr = address.format_map(connect_vars).strip() if address else ""
                        sni = resolve_host_sni(
                            export_host,
                            address=resolved_addr,
                            host_sni_override=host_sni_override,
                            resolved_sni=tls_client["sni"],
                        )
                        tls_extras = host_tls_extras(
                            export_host, fronted=bool(tls_client.get("tls_fronted"))
                        )
                        final_mask_obj = parse_json_object(export_host.get("final_mask"))
                        fm_param = marshal_final_mask(final_mask_obj)

                        host_inbound.update(
                            {
                                "port": client_port,
                                "sni": sni,
                                "host": req_host,
                                "tls": tls_client.get("client_tls")
                                or (inbound["tls"] if export_host["tls"] is None else export_host["tls"]),
                                "alpn": export_host["alpn"] or inbound.get("alpn"),
                                "ech_config_list": tls_extras.get("ech_config_list")
                                or tls_client.get("ech_config_list"),
                                "cert_pin_sha256": tls_extras.get("cert_pin_sha256")
                                or tls_client.get("cert_pin_sha256"),
                                "verify_peer_cert_by_name": tls_extras.get("verify_peer_cert_by_name"),
                                "final_mask_fm": fm_param,
                                "path": path,
                                "fp": default_tls_fingerprint(
                                    tls=host_inbound.get("tls") or "",
                                    existing=export_host["fingerprint"] or inbound.get("fp", ""),
                                ),
                                "ais": export_host["allowinsecure"]
                                or inbound.get("allowinsecure", ""),
                                "mux_enable": export_host["mux_enable"],
                                "fragment_setting": export_host["fragment_setting"],
                                "noise_setting": export_host["noise_setting"],
                                "random_user_agent": export_host["random_user_agent"],
                                "mihomo_ip_version": export_host.get("mihomo_ip_version") or "",
                                "_host_sockopt": parse_json_object(export_host.get("sockopt_params")),
                                "_host_final_mask": final_mask_obj,
                                "_host_mux_params": parse_mux_params(export_host),
                            }
                        )

                        export_settings = settings.model_dump()
                        if protocol.name == "VLESS" and export_host.get("vless_route"):
                            export_settings["id"] = apply_vless_route(
                                str(export_settings.get("id") or ""),
                                export_host.get("vless_route"),
                            )

                        from app.subscription.region_display import enrich_subscription_remark

                        remark = enrich_subscription_remark(
                            _sanitize_proxy_remark(
                                export_host["remark"].format_map(local_vars) + remark_suffix
                            ),
                            local_vars,
                        )

                        add_kwargs: dict = {}
                        if getattr(conf, "link_items", None) is not None:
                            add_kwargs = {
                                "region_flag": local_vars.get("REGION_FLAG") or "",
                                "region_name": local_vars.get("REGION_NAME") or "",
                            }

                        conf.add(
                            remark=remark,
                            address=resolved_addr,
                            inbound=host_inbound,
                            settings=export_settings,
                            **add_kwargs,
                        )

    return conf.render(reverse=reverse)


def _sanitize_proxy_remark(remark: str) -> str:
    """Strip legacy Marzban branding from host remarks in exported configs."""
    for old, new in (
        ("🚀 Marz", "Nexus"),
        ("Marz (", "Nexus ("),
        ("Marzban", "NexusPanel"),
        ("marzban", "NexusPanel"),
    ):
        remark = remark.replace(old, new)
    return remark


def encode_title(text: str) -> str:
    return f"base64:{base64.b64encode(text.encode()).decode()}"
