"""WARP outbound bootstrap: DNS bypass rules + stable WireGuard endpoint.

Also owns **clean removal**: when WARP credentials/outbounds disappear, routing
must fall back to ``DIRECT`` so clients are never black-holed on a missing tag.
"""
from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from copy import deepcopy
from typing import Any, Iterable, Optional, Sequence, Set

WARP_BYPASS_RULE: dict[str, Any] = {
    "type": "field",
    "domain": [
        "domain:engage.cloudflareclient.com",
        "domain:cloudflareclient.com",
        "domain:cloudflare.com",
    ],
    "outboundTag": "DIRECT",
}

WARP_DNS_DIRECT_RULE: dict[str, Any] = {
    "type": "field",
    "port": "53",
    "network": "udp",
    "outboundTag": "DIRECT",
}

WARP_DEFAULT_RULE: dict[str, Any] = {
    "type": "field",
    "network": "tcp,udp",
    "outboundTag": "warp",
}

DEFAULT_WARP_ENDPOINT_HOST = "engage.cloudflareclient.com"
DEFAULT_WARP_ENDPOINT_PORT = 2408
DNS_RESOLVE_TIMEOUT = 3.0

WARP_PINNED_IP_MARKER = "_nxWarpPinnedIp"


def is_warp_tag(tag: str | None) -> bool:
    """True for ``warp``, ``warp-2``, … (panel WARP account tags)."""
    t = str(tag or "").strip()
    return t == "warp" or t.startswith("warp-")


def _endpoint_looks_like_warp(endpoint: str) -> bool:
    ep = str(endpoint or "")
    return DEFAULT_WARP_ENDPOINT_HOST in ep


def _warp_outbounds(outbounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for ob in outbounds:
        if str(ob.get("protocol") or "") != "wireguard":
            continue
        tag = str(ob.get("tag") or "")
        settings = ob.get("settings") or {}
        peers = settings.get("peers") or []
        endpoint = ""
        if peers and isinstance(peers[0], dict):
            endpoint = str(peers[0].get("endpoint") or "")
        is_pinned_by_us = isinstance(settings, dict) and bool(settings.get(WARP_PINNED_IP_MARKER))
        if is_warp_tag(tag) or _endpoint_looks_like_warp(endpoint) or is_pinned_by_us:
            found.append(ob)
    return found


def find_warp_outbounds(outbounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Public entry point for callers that need live WARP wireguard outbound(s)."""
    return _warp_outbounds(outbounds)


def warp_outbound_tags(outbounds: Sequence[dict[str, Any]]) -> Set[str]:
    return {str(o.get("tag") or "") for o in _warp_outbounds(list(outbounds)) if o.get("tag")}


def resolve_warp_endpoint_ip(
    host: str = DEFAULT_WARP_ENDPOINT_HOST,
    port: int = DEFAULT_WARP_ENDPOINT_PORT,
    timeout: float = DNS_RESOLVE_TIMEOUT,
) -> str | None:
    """Resolve the WARP endpoint host, bounded by ``timeout``."""
    def _lookup() -> str | None:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
        except OSError:
            return None
        for info in infos:
            if info[0] == socket.AF_INET:
                return info[4][0]
        return infos[0][4][0] if infos else None

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_lookup)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeoutError:
            return None


def apply_warp_endpoint(outbound: dict[str, Any], host: str, port: int) -> bool:
    settings = outbound.get("settings")
    if not isinstance(settings, dict):
        return False
    peers = settings.get("peers")
    if not isinstance(peers, list) or not peers or not isinstance(peers[0], dict):
        return False
    peers[0]["endpoint"] = f"{host}:{int(port)}"
    settings[WARP_PINNED_IP_MARKER] = host
    return True


def find_working_warp_endpoint(
    candidates: Sequence[tuple[str, int]],
    probe,
) -> tuple[str, int] | None:
    for host, port in candidates:
        try:
            if probe(host, int(port)):
                return host, int(port)
        except Exception:
            continue
    return None


def _pin_warp_endpoint_ip(outbound: dict[str, Any]) -> bool:
    settings = outbound.get("settings")
    if not isinstance(settings, dict):
        return False
    peers = settings.get("peers")
    if not isinstance(peers, list) or not peers or not isinstance(peers[0], dict):
        return False
    current = str(peers[0].get("endpoint") or "")
    pinned = settings.get(WARP_PINNED_IP_MARKER)
    if pinned and current.startswith(str(pinned) + ":"):
        return False
    ip = resolve_warp_endpoint_ip()
    if not ip:
        return False
    return apply_warp_endpoint(outbound, ip, DEFAULT_WARP_ENDPOINT_PORT)


def _ensure_warp_outbound_settings(outbound: dict[str, Any]) -> bool:
    settings = outbound.setdefault("settings", {})
    if not isinstance(settings, dict):
        return False
    changed = False
    if settings.get("mtu") in (None, 0):
        settings["mtu"] = 1280
        changed = True
    if "noKernelTun" not in settings:
        settings["noKernelTun"] = True
        changed = True
    if _pin_warp_endpoint_ip(outbound):
        changed = True
    return changed


def _has_warp_bypass(rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        if str(rule.get("outboundTag") or "") != "DIRECT":
            continue
        domains = rule.get("domain") or []
        if isinstance(domains, list) and any(
            DEFAULT_WARP_ENDPOINT_HOST in str(d) for d in domains
        ):
            return True
    return False


def _has_dns_direct_rule(rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        if str(rule.get("outboundTag") or "") != "DIRECT":
            continue
        if str(rule.get("port") or "") == "53" and "udp" in str(rule.get("network") or ""):
            return True
    return False


def _is_catch_all_network_rule(rule: dict[str, Any]) -> bool:
    net = str(rule.get("network") or "")
    return (
        "tcp" in net
        and "udp" in net
        and not rule.get("domain")
        and not rule.get("ip")
        and not rule.get("source")
        and not rule.get("sourceIP")
        and not rule.get("inboundTag")
        and not rule.get("protocol")
        and not rule.get("port")
    )


def _has_warp_default_rule(rules: list[dict[str, Any]], tag: str = "warp") -> bool:
    for rule in rules:
        if str(rule.get("outboundTag") or "") == tag and _is_catch_all_network_rule(rule):
            return True
    return False


def _dedupe_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for rule in rules:
        key = json.dumps(rule, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(rule)
    return out


def rewrite_missing_warp_routes(
    payload: dict[str, Any],
    *,
    missing_tags: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Point routing that targets missing/removed WARP tags at ``DIRECT``."""
    data = deepcopy(payload)
    outbounds = list(data.get("outbounds") or [])
    present = {str(o.get("tag") or "") for o in outbounds if o.get("tag")}
    if missing_tags is None:
        targets = {
            str(r.get("outboundTag") or "")
            for r in ((data.get("routing") or {}).get("rules") or [])
            if is_warp_tag(str(r.get("outboundTag") or ""))
            and str(r.get("outboundTag") or "") not in present
        }
    else:
        targets = {str(t) for t in missing_tags if t}

    routing = data.get("routing")
    if not isinstance(routing, dict) or not targets:
        return data

    rules = list(routing.get("rules") or [])
    fixed: list[dict[str, Any]] = []
    for rule in rules:
        r = dict(rule)
        ot = str(r.get("outboundTag") or "")
        if ot in targets:
            r["outboundTag"] = "DIRECT"
        fixed.append(r)
    routing["rules"] = _dedupe_rules(fixed)
    return data


def strip_warp_from_config(
    payload: dict[str, Any],
    *,
    tags: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Remove WARP outbound(s) and repair routing so traffic uses ``DIRECT``.

    ``tags=None`` removes every WARP-like outbound. Otherwise only those tags.
    """
    data = deepcopy(payload)
    outbounds = list(data.get("outbounds") or [])
    if tags is None:
        remove_tags = warp_outbound_tags(outbounds)
        for rule in ((data.get("routing") or {}).get("rules") or []):
            ot = str(rule.get("outboundTag") or "")
            if is_warp_tag(ot):
                remove_tags.add(ot)
    else:
        remove_tags = {str(t) for t in tags if t}

    if not remove_tags:
        return rewrite_missing_warp_routes(data)

    data["outbounds"] = [o for o in outbounds if str(o.get("tag") or "") not in remove_tags]
    data = rewrite_missing_warp_routes(data, missing_tags=remove_tags)
    return data


def ensure_warp_exit(
    payload: dict[str, Any],
    outbound: dict[str, Any],
    *,
    as_default_exit: bool = True,
) -> dict[str, Any]:
    """Install/replace a WARP outbound and optionally make it the default exit."""
    data = deepcopy(payload)
    tag = str(outbound.get("tag") or "warp")
    outbound = deepcopy(outbound)
    outbound["tag"] = tag
    _ensure_warp_outbound_settings(outbound)

    existing = list(data.get("outbounds") or [])
    if as_default_exit:
        drop = warp_outbound_tags(existing) | {tag}
        outbounds = [o for o in existing if str(o.get("tag") or "") not in drop]
    else:
        outbounds = [o for o in existing if str(o.get("tag") or "") != tag]
    outbounds.append(outbound)
    data["outbounds"] = outbounds
    data = apply_warp_safe_routing(data)
    if as_default_exit:
        routing = data.setdefault("routing", {"domainStrategy": "IPIfNonMatch", "rules": []})
        rules = [
            r
            for r in list(routing.get("rules") or [])
            if not (
                is_warp_tag(str(r.get("outboundTag") or ""))
                and _is_catch_all_network_rule(r)
            )
            and not (
                str(r.get("outboundTag") or "") == "DIRECT"
                and _is_catch_all_network_rule(r)
            )
        ]
        rule = dict(WARP_DEFAULT_RULE)
        rule["outboundTag"] = tag
        rules.append(rule)
        routing["rules"] = _dedupe_rules(rules)
    return data


def apply_warp_safe_routing(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure WARP WireGuard can bootstrap when used as the default exit.

    Always rewrites routing that targets WARP tags with no matching outbound
    to ``DIRECT`` (including ``warp-2`` etc.).
    """
    data = rewrite_missing_warp_routes(deepcopy(payload))
    outbounds = list(data.get("outbounds") or [])
    warp_obs = _warp_outbounds(outbounds)
    if not warp_obs:
        return data

    outbound_changed = False
    for ob in outbounds:
        if ob in warp_obs and _ensure_warp_outbound_settings(ob):
            outbound_changed = True
    if outbound_changed:
        data["outbounds"] = outbounds

    routing = data.get("routing")
    if not isinstance(routing, dict):
        routing = {"domainStrategy": "IPIfNonMatch", "rules": []}
        data["routing"] = routing
    routing.setdefault("domainStrategy", "IPIfNonMatch")
    rules = list(routing.get("rules") or [])
    insert_at = 0

    if not _has_warp_bypass(rules):
        rules.insert(insert_at, dict(WARP_BYPASS_RULE))
        insert_at += 1

    if not _has_dns_direct_rule(rules):
        rules.insert(insert_at, dict(WARP_DNS_DIRECT_RULE))

    first_tag = str(outbounds[0].get("tag") or "") if outbounds else ""
    primary = str(warp_obs[0].get("tag") or "warp")
    if first_tag == primary and not _has_warp_default_rule(rules, primary):
        rule = dict(WARP_DEFAULT_RULE)
        rule["outboundTag"] = primary
        rules.append(rule)

    routing["rules"] = _dedupe_rules(rules)
    return data
