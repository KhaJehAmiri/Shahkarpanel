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

# Keep LAN / RFC1918 off WARP — otherwise captive portals and local APIs hang.
WARP_PRIVATE_DIRECT_RULE: dict[str, Any] = {
    "type": "field",
    "ip": ["geoip:private"],
    "outboundTag": "DIRECT",
}

API_INBOUND_RULE: dict[str, Any] = {
    "type": "field",
    "inboundTag": ["API_INBOUND"],
    "outboundTag": "API",
}

WARP_DEFAULT_RULE: dict[str, Any] = {
    "type": "field",
    "network": "tcp,udp",
    "outboundTag": "warp",
}

# Marker on domain→WARP rules / balancer so rebuilds can strip them cleanly.
SENSITIVE_WARP_MARK = "_nxSensitiveWarp"
SENSITIVE_WARP_BALANCER_TAG = "warp-sensitive-lb"
# Bump when the sensitive domain/geosite lists change so keep-live reconnects
# re-push exit cores instead of leaving stale routing on the node.
WARP_SENSITIVE_POLICY_REV = 7

# Rewrite dest to sniffed SNI/Host. ``routeOnly: true`` + ``AsIs`` on Xray 26.x
# often leaves the destination as a raw IP, so Google/Gemini never match the
# domain→WARP rules and stay on the datacenter IP (HTTP 403).
SENSITIVE_WARP_SNIFFING: dict[str, Any] = {
    "enabled": True,
    "destOverride": ["http", "tls", "quic"],
    "routeOnly": False,
}

SENSITIVE_WARP_QUIC_MARK = "_nxSensitiveWarpQuic"

# Server-side split: only location-sensitive services exit via WARP.
# Same inbound/configs for users — Xray routing picks the path by SNI/domain.
# Prefer explicit ``domain:`` entries (always work). geosite tags are best-effort
# extras when geosite.dat is present on the node.
SENSITIVE_WARP_DOMAINS: list[str] = [
    # Prefer explicit domains — always work even if geosite.dat is old/minimal.
    # geosite tags are appended as separate rules so a missing tag cannot
    # invalidate the whole domain list.
    "domain:googleapis.com",
    "domain:gstatic.com",
    "domain:googleusercontent.com",
    "domain:googlevideo.com",
    "domain:ytimg.com",
    "domain:ggpht.com",
    "domain:youtu.be",
    "domain:youtube.com",
    "domain:google.com",
    "domain:accounts.google.com",
    "domain:play.google.com",
    "domain:clients6.google.com",
    # Gemini / Bard / AI Studio / NotebookLM
    "domain:gemini.google.com",
    "domain:gemini.google",
    "domain:gemini.gstatic.com",
    "domain:bard.google.com",
    "domain:aistudio.google.com",
    "domain:ai.google.dev",
    "domain:ai.studio",
    "domain:makersuite.google.com",
    "domain:generativelanguage.googleapis.com",
    "domain:aisandbox-pa.googleapis.com",
    "domain:aicode.googleapis.com",
    "domain:aida.googleapis.com",
    "domain:cloudaicompanion.googleapis.com",
    "domain:cloudcode-pa.googleapis.com",
    "domain:daily-cloudcode-pa.googleapis.com",
    "domain:notebooklm.googleapis.com",
    "domain:notebooklm-pa.googleapis.com",
    "domain:notebooklm.google.com",
    "domain:notebooklm.google",
    "domain:notebook.google.com",
    "domain:alkalimakersuite-pa.clients6.google.com",
    "domain:alkalicore-pa.clients6.google.com",
    "domain:webchannel-alkalimakersuite-pa.clients6.google.com",
    "domain:robinfrontend-pa.googleapis.com",
    "domain:proactivebackend-pa.googleapis.com",
    "domain:geller-pa.googleapis.com",
    "domain:deepmind.com",
    "domain:deepmind.google",
    "domain:generativeai.google",
    "domain:labs.google",
    "domain:labs.google.com",
    "domain:jules.google",
    "domain:jules.google.com",
    "domain:flow.google",
    "domain:flow.google.com",
    "domain:flow.withgoogle.com",
    "domain:veo.google",
    "domain:veo.googleapis.com",
    "domain:fx.google",
    "domain:musicfx.google",
    "domain:musicfx.withgoogle.com",
    "domain:imagen.google",
    "domain:whisk.google",
    "domain:whisk.google.com",
    "domain:aitestkitchen.withgoogle.com",
    "domain:experiments.withgoogle.com",
    "domain:flow-pa.googleapis.com",
    "domain:labs-pa.googleapis.com",
    "domain:fx-pa.googleapis.com",
    "domain:alkali-pa.googleapis.com",
    "domain:opal.google",
    "domain:opal.google.com",
    "domain:stitch.withgoogle.com",
    # Other location-sensitive AI
    "domain:chatgpt.com",
    "domain:openai.com",
    "domain:api.openai.com",
    "domain:claude.ai",
    "domain:anthropic.com",
    "domain:api.anthropic.com",
    # Spotify (web + app + CDN hostnames that include "spotify")
    "domain:spotify.com",
    "domain:spoti.fi",
    "domain:scdn.co",
    "domain:pscdn.co",
    "domain:spotifycdn.com",
    "domain:spotifycdn.net",
    "keyword:spotify",
]

# Optional geosite packs (separate rules; skipped harmlessly if dat lacks them
# only when Xray still accepts unknown codes — keep to widely-present names).
SENSITIVE_WARP_GEOSITES: list[str] = [
    "geosite:google",
    "geosite:youtube",
    "geosite:openai",
    "geosite:spotify",
]

# WireGuard and sing-box (Hysteria2/TUIC) almost never present a domain:
# the OS / sing-box DNS already resolved, so dest is an IP. Domain rules
# then never match and the flow exits DIRECT (datacenter 403) while VLESS
# still works because the client sends the hostname in the protocol header.
# geoip:google covers YouTube/Gemini/Google even when dest is a raw IP.
SENSITIVE_WARP_IPS: list[str] = [
    "geoip:google",
]

_SENSITIVE_DOMAIN_CHUNK = 48


def parse_warp_tags(raw: str | None) -> list[str]:
    """Parse ``warp`` or ``warp,warp-2,warp-3`` into a de-duplicated tag list."""
    text = str(raw or "").strip() or "warp"
    tags: list[str] = []
    seen: set[str] = set()
    for part in text.replace(";", ",").split(","):
        tag = part.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags or ["warp"]


def primary_warp_tag(raw: str | None) -> str:
    return parse_warp_tags(raw)[0]

# Client WG MTU when the node exits via WARP (outer tunnel is 1280).
WARP_NESTED_CLIENT_MTU = 1280
WARP_OUTBOUND_MTU = 1280
WARP_OUTBOUND_WORKERS = 4

# Plain UDP resolvers — DoH through WARP causes recursive latency (apps hang
# while small Cloudflare IP checks still succeed).
WARP_PLAIN_DNS_SERVERS = ["1.1.1.1", "8.8.8.8", "1.0.0.1"]


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
    # Always pin WARP MTU — a higher value black-holes large HTTPS packets.
    if settings.get("mtu") != WARP_OUTBOUND_MTU:
        settings["mtu"] = WARP_OUTBOUND_MTU
        changed = True
    if settings.get("workers") != WARP_OUTBOUND_WORKERS:
        settings["workers"] = WARP_OUTBOUND_WORKERS
        changed = True
    if settings.get("noKernelTun") is not True:
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


def _is_api_inbound_rule(rule: dict[str, Any]) -> bool:
    if not isinstance(rule, dict):
        return False
    return str(rule.get("outboundTag") or "") == "API" and "API_INBOUND" in (
        rule.get("inboundTag") or []
    )


def pin_api_inbound_route(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep ``API_INBOUND → API`` ahead of ``geoip:private → DIRECT``.

    WARP bootstrap inserts a private-IP DIRECT rule at the front so LAN
    never enters the tunnel. The panel Stats/Handler gRPC inbound is
    dokodemo to ``127.0.0.1``, which *is* private — if that DIRECT rule
    wins, probes show ``API_INBOUND -> DIRECT``, the API socket dies, and
    health-check restarts the core in a loop (often colliding on in2/3334).
    """
    data = payload if isinstance(payload, dict) else dict(payload)
    has_api_ib = any(
        isinstance(ib, dict) and str(ib.get("tag") or "") == "API_INBOUND"
        for ib in (data.get("inbounds") or [])
    )
    routing = data.get("routing")
    if not isinstance(routing, dict):
        if not has_api_ib:
            return data
        routing = {"domainStrategy": "IPIfNonMatch", "rules": []}
        data["routing"] = routing
    rules = [r for r in list(routing.get("rules") or []) if isinstance(r, dict)]
    api = [r for r in rules if _is_api_inbound_rule(r)]
    rest = [r for r in rules if not _is_api_inbound_rule(r)]
    if not api:
        if not has_api_ib:
            return data
        api = [dict(API_INBOUND_RULE)]
    routing["rules"] = api + rest
    data["routing"] = routing
    return data


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


def _is_bootstrap_direct_rule(rule: dict[str, Any]) -> bool:
    """Cloudflare / DNS / LAN DIRECT escapes that must stay ahead of WARP."""
    if str(rule.get("outboundTag") or "") != "DIRECT":
        return False
    if _is_catch_all_network_rule(rule):
        return False
    domains = rule.get("domain") or []
    if isinstance(domains, list) and any(
        DEFAULT_WARP_ENDPOINT_HOST in str(d) for d in domains
    ):
        return True
    ips = rule.get("ip") or []
    if isinstance(ips, list) and any("geoip:private" in str(i) for i in ips):
        return True
    return str(rule.get("port") or "") == "53"


def insert_rule_before_catchall(
    rules: list[dict[str, Any]],
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    """Place a specific rule ahead of catch-all ``tcp,udp`` DIRECT/WARP.

    Xray first-match-wins. Appending inbound→WARP after catch-all DIRECT
    silently sends every inbound to DIRECT — the usual dashboard pitfall.
    """
    out = list(rules)
    if _is_catch_all_network_rule(rule):
        out.append(rule)
        return out
    for i, existing in enumerate(out):
        if isinstance(existing, dict) and _is_catch_all_network_rule(existing):
            out.insert(i, rule)
            return out
    out.append(rule)
    return out


def _unshadow_warp_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep inbound/domain WARP rules in front of catch-all DIRECT.

    A catch-all WARP (full-exit) also drops a later/earlier catch-all DIRECT
    so the default exit is actually WARP.
    """
    api: list[dict[str, Any]] = []
    bootstrap: list[dict[str, Any]] = []
    specific_warp: list[dict[str, Any]] = []
    specific_other: list[dict[str, Any]] = []
    catch_warp: list[dict[str, Any]] = []
    catch_direct: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        ot = str(rule.get("outboundTag") or "")
        balancer = str(rule.get("balancerTag") or "")
        if _is_api_inbound_rule(rule):
            api.append(rule)
        elif ot == "DIRECT" and _is_catch_all_network_rule(rule):
            catch_direct.append(rule)
        elif is_warp_tag(ot) and _is_catch_all_network_rule(rule):
            catch_warp.append(rule)
        elif _is_bootstrap_direct_rule(rule):
            bootstrap.append(rule)
        elif is_warp_tag(ot) or balancer == SENSITIVE_WARP_BALANCER_TAG:
            specific_warp.append(rule)
        else:
            specific_other.append(rule)
    if catch_warp:
        catch_direct = []
    return _dedupe_rules(
        api + bootstrap + specific_warp + specific_other + catch_warp + catch_direct
    )


def _sanitize_direct_outbound(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop freedom ``finalRules`` that would black-hole public DIRECT traffic.

    An allow-only ``geoip:private`` list breaks Cloudflare/DNS bypass and the
    WARP handshake path when those flows are routed to DIRECT.
    """
    outbounds = list(payload.get("outbounds") or [])
    changed = False
    for ob in outbounds:
        if not isinstance(ob, dict):
            continue
        if str(ob.get("tag") or "") != "DIRECT" or str(ob.get("protocol") or "") != "freedom":
            continue
        settings = ob.get("settings")
        if not isinstance(settings, dict) or "finalRules" not in settings:
            continue
        settings = dict(settings)
        settings.pop("finalRules", None)
        if settings:
            ob["settings"] = settings
        else:
            ob.pop("settings", None)
        changed = True
    if changed:
        payload["outbounds"] = outbounds
    return payload


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
    data = strip_sensitive_warp_routing(data)
    data = rewrite_missing_warp_routes(data, missing_tags=remove_tags)
    return data


def apply_warp_dns_for_exit(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace DoH DNS with plain UDP resolvers when WARP is the default exit.

    ``https://1.1.1.1/dns-query`` would otherwise be routed through the WARP
    catch-all (TCP/443), so every name lookup waits on the tunnel — apps never
    open even though Cloudflare IP detection works.
    """
    data = deepcopy(payload)
    dns = data.get("dns")
    if not isinstance(dns, dict):
        dns = {}
    servers_in = list(dns.get("servers") or [])
    servers_out: list[Any] = []
    for s in servers_in:
        if isinstance(s, str):
            if s.startswith("https://") or s.startswith("h3://") or s.startswith("quic://"):
                continue
            servers_out.append(s)
            continue
        if isinstance(s, dict):
            addr = str(s.get("address") or "")
            if addr.startswith("https://") or addr.startswith("h3://") or addr.startswith("quic://"):
                continue
            servers_out.append(s)
            continue
        servers_out.append(s)
    have = {s for s in servers_out if isinstance(s, str)}
    for plain in WARP_PLAIN_DNS_SERVERS:
        if plain not in have:
            servers_out.append(plain)
            have.add(plain)
    if not servers_out:
        servers_out = list(WARP_PLAIN_DNS_SERVERS)
    dns["servers"] = servers_out
    dns.setdefault("queryStrategy", "UseIPv4")
    data["dns"] = dns
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
        data = apply_warp_dns_for_exit(data)
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
        # Prefer bootstrap rules at the front so inbound→tunnel rules cannot
        # shadow Cloudflare/DNS/private DIRECT escapes for general traffic.
        front: list[dict[str, Any]] = []
        if not _has_warp_bypass(rules):
            front.append(dict(WARP_BYPASS_RULE))
        if not _has_private_direct_rule(rules):
            front.append(dict(WARP_PRIVATE_DIRECT_RULE))
        if not _has_dns_direct_rule(rules):
            front.append(dict(WARP_DNS_DIRECT_RULE))
        # Move existing bootstrap rules to the front too.
        bootstrap: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        for r in rules:
            ot = str(r.get("outboundTag") or "")
            if ot == "DIRECT" and (
                (isinstance(r.get("domain"), list) and any(
                    DEFAULT_WARP_ENDPOINT_HOST in str(d) for d in (r.get("domain") or [])
                ))
                or (isinstance(r.get("ip"), list) and any(
                    "geoip:private" in str(i) for i in (r.get("ip") or [])
                ))
                or (str(r.get("port") or "") == "53")
            ):
                bootstrap.append(r)
            else:
                rest.append(r)
        rule = dict(WARP_DEFAULT_RULE)
        rule["outboundTag"] = tag
        routing["rules"] = _dedupe_rules(front + bootstrap + rest + [rule])
    return data


def _has_private_direct_rule(rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        if str(rule.get("outboundTag") or "") != "DIRECT":
            continue
        ips = rule.get("ip") or []
        if isinstance(ips, list) and any("geoip:private" in str(i) for i in ips):
            return True
    return False


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

    if not _has_private_direct_rule(rules):
        rules.insert(insert_at, dict(WARP_PRIVATE_DIRECT_RULE))
        insert_at += 1

    if not _has_dns_direct_rule(rules):
        rules.insert(insert_at, dict(WARP_DNS_DIRECT_RULE))

    # Never add a catch-all→WARP when sensitive split rules are active — that
    # would send all traffic through WARP and defeat the split.
    has_sensitive = any(
        isinstance(r, dict)
        and (
            r.get(SENSITIVE_WARP_MARK)
            or r.get(SENSITIVE_WARP_QUIC_MARK)
            or str(r.get("balancerTag") or "") == SENSITIVE_WARP_BALANCER_TAG
            or (
                is_warp_tag(str(r.get("outboundTag") or ""))
                and (r.get("domain") or r.get("ip"))
            )
        )
        for r in rules
    )
    first_tag = str(outbounds[0].get("tag") or "") if outbounds else ""
    primary = str(warp_obs[0].get("tag") or "warp")
    if (
        not has_sensitive
        and first_tag == primary
        and not _has_warp_default_rule(rules, primary)
    ):
        rule = dict(WARP_DEFAULT_RULE)
        rule["outboundTag"] = primary
        rules.append(rule)

    routing["rules"] = _unshadow_warp_rules(_dedupe_rules(rules))
    data = _sanitize_direct_outbound(data)
    if _has_warp_default_rule(routing["rules"], primary):
        data = apply_warp_dns_for_exit(data)
    return pin_api_inbound_route(data)


def _is_sensitive_warp_rule(rule: dict[str, Any]) -> bool:
    if not isinstance(rule, dict):
        return False
    if rule.get(SENSITIVE_WARP_MARK) or rule.get(SENSITIVE_WARP_QUIC_MARK):
        return True
    if str(rule.get("balancerTag") or "") == SENSITIVE_WARP_BALANCER_TAG:
        return True
    if is_warp_tag(str(rule.get("outboundTag") or "")) and (
        rule.get("domain") or rule.get("ip")
    ):
        return True
    if (
        str(rule.get("outboundTag") or "") == "BLOCK"
        and str(rule.get("network") or "") == "udp"
        and str(rule.get("port") or "") == "443"
        and rule.get("inboundTag")
    ):
        return True
    return False


def strip_sensitive_warp_routing(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive-split domain rules and the dedicated balancer."""
    data = deepcopy(payload)
    routing = data.get("routing")
    if isinstance(routing, dict):
        rules = [
            r
            for r in list(routing.get("rules") or [])
            if not _is_sensitive_warp_rule(r)
        ]
        routing["rules"] = rules
        balancers = [
            b
            for b in list(routing.get("balancers") or [])
            if not (
                isinstance(b, dict)
                and (
                    b.get(SENSITIVE_WARP_MARK)
                    or str(b.get("tag") or "") == SENSITIVE_WARP_BALANCER_TAG
                )
            )
        ]
        if balancers:
            routing["balancers"] = balancers
        else:
            routing.pop("balancers", None)
    return data


def _sensitive_domain_rules(target: dict[str, Any]) -> list[dict[str, Any]]:
    """Build chunked domain rules pointing at outboundTag or balancerTag."""
    rules: list[dict[str, Any]] = []
    domains = list(SENSITIVE_WARP_DOMAINS)
    for i in range(0, len(domains), _SENSITIVE_DOMAIN_CHUNK):
        part = domains[i : i + _SENSITIVE_DOMAIN_CHUNK]
        rule: dict[str, Any] = {
            "type": "field",
            "domain": part,
        }
        rule.update(target)
        rules.append(rule)
    # One geosite per rule so a missing pack cannot void explicit domains.
    for g in SENSITIVE_WARP_GEOSITES:
        rule = {
            "type": "field",
            "domain": [g],
        }
        rule.update(target)
        rules.append(rule)
    # IP fallback so WireGuard / sing-box (dest already an IP) still hit WARP.
    for ip in SENSITIVE_WARP_IPS:
        rule = {
            "type": "field",
            "ip": [ip],
        }
        rule.update(target)
        rules.append(rule)
    return rules


def _inbound_needs_sensitive_sniffing(ib: dict[str, Any]) -> bool:
    """User-facing inbounds that must rewrite SNI so domain→WARP rules match."""
    tag = str(ib.get("tag") or "")
    proto = str(ib.get("protocol") or "")
    if not tag or tag in {"API_INBOUND", "api"} or tag.upper().startswith("API"):
        return False
    if proto in {"blackhole", "dns"}:
        return False
    if proto == "wireguard" or "xray-wg-in" in tag or tag.endswith("-singbox-in"):
        return True
    if tag.startswith("tunnel-") and tag.endswith("-exit"):
        return True
    if tag.endswith("-warp-tproxy"):
        return True
    if tag.startswith("in"):
        return True
    if proto in {"vless", "vmess", "trojan", "shadowsocks", "socks", "http"}:
        return True
    sockopt = ((ib.get("streamSettings") or {}) if isinstance(ib.get("streamSettings"), dict) else {}).get("sockopt") or {}
    if proto == "dokodemo-door" and str(sockopt.get("tproxy") or "").lower() == "tproxy":
        return True
    return False


def _sensitive_quic_inbound_tags(payload: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for ib in list(payload.get("inbounds") or []):
        if not isinstance(ib, dict):
            continue
        tag = str(ib.get("tag") or "")
        if tag and _inbound_needs_sensitive_sniffing(ib):
            tags.append(tag)
    return tags


def _ensure_block_outbound(payload: dict[str, Any]) -> None:
    outbounds = list(payload.get("outbounds") or [])
    if any(str(o.get("tag") or "") == "BLOCK" for o in outbounds if isinstance(o, dict)):
        return
    outbounds.append({"tag": "BLOCK", "protocol": "blackhole", "settings": {}})
    payload["outbounds"] = outbounds


def _sensitive_quic_block_rule(inbound_tags: Sequence[str]) -> dict[str, Any]:
    """Force HTTP/2 for tunneled apps so SNI is visible and domain→WARP matches.

    Chrome/YouTube/Gemini prefer QUIC; UDP/443 to an IP never matches domain
    rules and exits DIRECT (datacenter 403). Blocking QUIC on tunnel/TPROXY
    inbounds makes the client fall back to TCP/TLS.
    """
    return {
        "type": "field",
        "inboundTag": list(inbound_tags),
        "network": "udp",
        "port": "443",
        "outboundTag": "BLOCK",
    }


def ensure_tunnel_exit_sniffing(payload: dict[str, Any]) -> dict[str, Any]:
    """Enable dest-rewriting sniffing on every user inbound of a WARP exit.

    Tunnel-exit, TPROXY, and public VLESS (in1/in2/in3) all see Google as an
    IP+QUIC flow unless sniffing rewrites SNI. ``routeOnly`` left those on
    DIRECT (datacenter 403) except the location whose clients already hit the
    patched tunnel-exit path.
    """
    data = payload if isinstance(payload, dict) else dict(payload)
    sniff = dict(SENSITIVE_WARP_SNIFFING)
    changed = False
    inbounds = list(data.get("inbounds") or [])
    for ib in inbounds:
        if not isinstance(ib, dict) or not _inbound_needs_sensitive_sniffing(ib):
            continue
        if ib.get("sniffing") != sniff:
            ib["sniffing"] = dict(sniff)
            changed = True
    if changed:
        data["inbounds"] = inbounds
    return data


def refresh_sensitive_quic_block(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep UDP/443 blackholed on every sniffed inbound (including TPROXY added later)."""
    data = payload if isinstance(payload, dict) else dict(payload)
    tags = _sensitive_quic_inbound_tags(data)
    routing = data.get("routing")
    if not isinstance(routing, dict):
        routing = {"rules": []}
        data["routing"] = routing
    rules = [
        r
        for r in list(routing.get("rules") or [])
        if not (
            isinstance(r, dict)
            and str(r.get("outboundTag") or "") == "BLOCK"
            and str(r.get("network") or "") == "udp"
            and str(r.get("port") or "") == "443"
            and r.get("inboundTag")
        )
    ]
    if tags:
        _ensure_block_outbound(data)
        insert_at = 0
        for i, r in enumerate(rules):
            if str(r.get("outboundTag") or "") == "DIRECT":
                insert_at = i + 1
            else:
                break
        rules.insert(insert_at, _sensitive_quic_block_rule(tags))
    routing["rules"] = rules
    return data


def ensure_warp_sensitive_exit(
    payload: dict[str, Any],
    outbounds: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Install one or more WARP outbounds and route only sensitive domains to them.

    Default exit stays ``DIRECT`` (or whatever non-WARP path the node already
    uses). Multiple outbounds get an Xray balancer (``random``) for load-share.
    """
    data = strip_sensitive_warp_routing(deepcopy(payload))
    prepared: list[dict[str, Any]] = []
    tags: list[str] = []
    for raw in outbounds:
        if not isinstance(raw, dict):
            continue
        ob = deepcopy(raw)
        tag = str(ob.get("tag") or "").strip()
        if not tag:
            continue
        ob["tag"] = tag
        _ensure_warp_outbound_settings(ob)
        prepared.append(ob)
        tags.append(tag)
    if not prepared:
        return data

    existing = list(data.get("outbounds") or [])
    drop = set(tags) | {SENSITIVE_WARP_BALANCER_TAG}
    drop |= {str(o.get("tag") or "") for o in _warp_outbounds(existing)}
    merged = [o for o in existing if str(o.get("tag") or "") not in drop]
    merged.extend(prepared)
    data["outbounds"] = merged
    _ensure_block_outbound(data)

    data = apply_warp_dns_for_exit(data)
    data = apply_warp_safe_routing(data)
    data = strip_sensitive_warp_routing(data)
    data = ensure_tunnel_exit_sniffing(data)

    routing = data.setdefault("routing", {"domainStrategy": "IPIfNonMatch", "rules": []})
    # IPIfNonMatch: sniffed/rewritten domains match WARP rules; unmatched IPs stay IP.
    routing["domainStrategy"] = "IPIfNonMatch"

    rules = [
        r
        for r in list(routing.get("rules") or [])
        if not (
            is_warp_tag(str(r.get("outboundTag") or ""))
            and _is_catch_all_network_rule(r)
        )
    ]

    if len(tags) == 1:
        target: dict[str, Any] = {"outboundTag": tags[0]}
        routing.pop("balancers", None)
    else:
        balancers = [
            b
            for b in list(routing.get("balancers") or [])
            if str(b.get("tag") or "") != SENSITIVE_WARP_BALANCER_TAG
            and not (isinstance(b, dict) and b.get(SENSITIVE_WARP_MARK))
        ]
        # Do not put custom marker fields on balancers — some Xray builds are
        # strict about balancer JSON shape.
        balancers.append(
            {
                "tag": SENSITIVE_WARP_BALANCER_TAG,
                "selector": tags,
                "strategy": {"type": "random"},
            }
        )
        routing["balancers"] = balancers
        target = {"balancerTag": SENSITIVE_WARP_BALANCER_TAG}

    sensitive_rules = _sensitive_domain_rules(target)

    front: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for r in rules:
        ot = str(r.get("outboundTag") or "")
        if ot == "DIRECT" and (
            (
                isinstance(r.get("domain"), list)
                and any(
                    DEFAULT_WARP_ENDPOINT_HOST in str(d)
                    for d in (r.get("domain") or [])
                )
            )
            or (
                isinstance(r.get("ip"), list)
                and any("geoip:private" in str(i) for i in (r.get("ip") or []))
            )
            or (str(r.get("port") or "") == "53")
        ):
            front.append(r)
        else:
            rest.append(r)

    if not _has_warp_bypass(front + rest):
        front.insert(0, dict(WARP_BYPASS_RULE))
    if not _has_private_direct_rule(front + rest):
        front.append(dict(WARP_PRIVATE_DIRECT_RULE))
    if not _has_dns_direct_rule(front + rest):
        front.append(dict(WARP_DNS_DIRECT_RULE))

    routing["rules"] = _dedupe_rules(front + sensitive_rules + rest)
    return pin_api_inbound_route(refresh_sensitive_quic_block(data))


def singbox_warp_socks_port(node_id: int) -> int:
    return 23000 + (int(node_id) % 1000)


def singbox_warp_inbound_tag(node_id: int) -> str:
    return f"node-{int(node_id)}-singbox-in"


def inject_singbox_warp_inbound(payload: dict[str, Any], node_id: int) -> dict[str, Any]:
    """Local SOCKS so sing-box (Hysteria2/TUIC) uses the same Xray WARP split."""
    data = payload if isinstance(payload, dict) else dict(payload)
    tag = singbox_warp_inbound_tag(node_id)
    inbound = {
        "tag": tag,
        "listen": "127.0.0.1",
        "port": singbox_warp_socks_port(node_id),
        "protocol": "socks",
        "settings": {"udp": True, "auth": "noauth"},
        "sniffing": dict(SENSITIVE_WARP_SNIFFING),
    }
    inbounds = [
        ib
        for ib in list(data.get("inbounds") or [])
        if not (isinstance(ib, dict) and ib.get("tag") == tag)
    ]
    inbounds.append(inbound)
    data["inbounds"] = inbounds
    return data
