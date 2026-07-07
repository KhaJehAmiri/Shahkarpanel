"""WARP outbound bootstrap: DNS bypass rules + stable WireGuard endpoint."""
from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from copy import deepcopy
from typing import Any

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

# Persisted (written into xray_config.json, harmless extra field Xray
# ignores — same trick as NXPANEL_INBOUND_KIND) marker recording which IP we
# last pinned onto this outbound. Lets us tell "an IP we chose" apart from an
# admin's manually configured endpoint across process restarts, so we can
# safely re-resolve/rotate it (self-heal if Cloudflare's anycast IP goes
# stale) without ever clobbering a manually configured outbound. A plain
# in-memory cache would not survive a panel restart, which is exactly when
# you'd most want a fresh lookup.
WARP_PINNED_IP_MARKER = "_nxWarpPinnedIp"


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
        # Non-default tags (multi-account WARP, e.g. "warp-2") are only
        # matched by hostname the first time around — once pinned to an IP
        # the hostname is gone, so the persisted marker is what keeps them
        # recognizable as "ours" across later normalize passes / health checks.
        is_pinned_by_us = isinstance(settings, dict) and bool(settings.get(WARP_PINNED_IP_MARKER))
        if tag == "warp" or DEFAULT_WARP_ENDPOINT_HOST in endpoint or is_pinned_by_us:
            found.append(ob)
    return found


def find_warp_outbounds(outbounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Public entry point for callers (e.g. the WARP health-check job) that
    need to locate the live WARP wireguard outbound(s) in a config."""
    return _warp_outbounds(outbounds)


def resolve_warp_endpoint_ip(
    host: str = DEFAULT_WARP_ENDPOINT_HOST,
    port: int = DEFAULT_WARP_ENDPOINT_PORT,
    timeout: float = DNS_RESOLVE_TIMEOUT,
) -> str | None:
    """Resolve the WARP endpoint host, bounded by ``timeout``.

    ``socket.getaddrinfo`` ignores ``socket.setdefaulttimeout`` (it calls the
    system resolver directly), so a broken/censored DNS path can otherwise
    hang the calling request for a long time. Run it in a worker thread and
    give up after ``timeout`` seconds instead.
    """
    def _lookup() -> str | None:
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            return None
        return infos[0][4][0] if infos else None

    # Don't use the executor as a context manager: shutdown(wait=True) would
    # block on the lookup thread even after we've already given up on it,
    # defeating the whole point of the timeout.
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_lookup)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        return None
    finally:
        pool.shutdown(wait=False)


def _pin_warp_endpoint_ip(outbound: dict[str, Any]) -> bool:
    settings = outbound.get("settings")
    if not isinstance(settings, dict):
        return False
    peers = settings.get("peers")
    if not isinstance(peers, list) or not peers:
        return False
    peer = peers[0]
    if not isinstance(peer, dict):
        return False
    endpoint = str(peer.get("endpoint") or "")
    if not endpoint:
        return False
    host_part = endpoint.rsplit(":", 1)[0]
    is_hostname = DEFAULT_WARP_ENDPOINT_HOST in endpoint
    # Re-resolve endpoints we previously pinned too, so a stale/blocked
    # anycast IP can self-heal instead of being stuck forever — the marker
    # survives on disk across restarts. Endpoints the admin pointed
    # elsewhere manually (no marker, not our hostname) are left untouched.
    is_our_pinned_ip = bool(settings.get(WARP_PINNED_IP_MARKER)) and host_part == settings.get(
        WARP_PINNED_IP_MARKER
    )
    if not is_hostname and not is_our_pinned_ip:
        return False
    ip = resolve_warp_endpoint_ip()
    if not ip:
        return False
    settings[WARP_PINNED_IP_MARKER] = ip
    new_endpoint = f"{ip}:{DEFAULT_WARP_ENDPOINT_PORT}"
    if endpoint == new_endpoint:
        return False
    peer["endpoint"] = new_endpoint
    return True


def parse_endpoint(value: str) -> tuple[str, int] | None:
    """Parse an "ip:port" string. Returns None if malformed."""
    text = str(value or "").strip()
    if ":" not in text:
        return None
    host, _, port_str = text.rpartition(":")
    if not host or not port_str.isdigit():
        return None
    return host, int(port_str)


def build_probe_outbound(outbound: dict[str, Any], host: str, port: int) -> dict[str, Any] | None:
    """Return a deep-copied outbound with peer[0]'s endpoint swapped to
    ``host:port``, for testing a candidate without mutating the live config."""
    candidate = deepcopy(outbound)
    settings = candidate.get("settings")
    if not isinstance(settings, dict):
        return None
    peers = settings.get("peers")
    if not isinstance(peers, list) or not peers or not isinstance(peers[0], dict):
        return None
    peers[0]["endpoint"] = f"{host}:{port}"
    return candidate


def apply_warp_endpoint(outbound: dict[str, Any], host: str, port: int) -> bool:
    """Pin ``outbound`` onto ``host:port`` and record it as ours (marker), so
    later normalize passes / health checks recognize and can keep managing
    it. Returns True if the endpoint actually changed."""
    settings = outbound.setdefault("settings", {})
    if not isinstance(settings, dict):
        return False
    peers = settings.get("peers")
    if not isinstance(peers, list) or not peers or not isinstance(peers[0], dict):
        return False
    new_endpoint = f"{host}:{port}"
    changed = str(peers[0].get("endpoint") or "") != new_endpoint
    peers[0]["endpoint"] = new_endpoint
    settings[WARP_PINNED_IP_MARKER] = host
    return changed


def candidate_endpoints() -> list[tuple[str, int]]:
    """Ordered list of endpoints to try when the current one is confirmed
    broken: a fresh DNS lookup of the default host first (cheap, and in case
    Cloudflare's anycast answer legitimately changed), then the configured
    fallback IP:port candidates (``WARP_CANDIDATE_ENDPOINTS``) — needed
    because the default hostname normally resolves to the *same* address
    every time, so re-resolving alone can't route around a blocked IP."""
    from config import WARP_CANDIDATE_ENDPOINTS

    out: list[tuple[str, int]] = []
    fresh_ip = resolve_warp_endpoint_ip()
    if fresh_ip:
        out.append((fresh_ip, DEFAULT_WARP_ENDPOINT_PORT))
    for raw in WARP_CANDIDATE_ENDPOINTS:
        parsed = parse_endpoint(raw)
        if parsed and parsed not in out:
            out.append(parsed)
    return out


def find_working_warp_endpoint(
    outbound: dict[str, Any],
    prober,
    candidates: list[tuple[str, int]] | None = None,
) -> tuple[str, int] | None:
    """Try each candidate endpoint in order and return the first ``prober``
    reports as working, or None if all fail.

    ``prober(candidate_outbound) -> bool`` is injected so this stays a pure,
    fast-to-test function — the real prober (in app/jobs/warp_health.py)
    spins up a throwaway Xray process per candidate, which is far too slow
    and side-effecting for unit tests.
    """
    for host, port in candidates if candidates is not None else candidate_endpoints():
        probe = build_probe_outbound(outbound, host, port)
        if probe is None:
            continue
        try:
            if prober(probe):
                return host, port
        except Exception:
            continue
    return None


def _ensure_warp_outbound_settings(outbound: dict[str, Any]) -> bool:
    changed = False
    settings = outbound.setdefault("settings", {})
    if not isinstance(settings, dict):
        return changed
    if not settings.get("workers"):
        settings["workers"] = 2
        changed = True
    if settings.get("noKernelTun") is not True:
        settings["noKernelTun"] = True
        changed = True
    if _pin_warp_endpoint_ip(outbound):
        changed = True
    return changed


def _rule_domains(rule: dict[str, Any]) -> list[str]:
    dom = rule.get("domain")
    if isinstance(dom, list):
        return [str(d) for d in dom]
    if dom:
        return [str(dom)]
    return []


def _has_warp_bypass(rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        if str(rule.get("outboundTag") or "") != "DIRECT":
            continue
        if any("cloudflareclient" in d for d in _rule_domains(rule)):
            return True
    return False


def _has_dns_direct_rule(rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        if str(rule.get("outboundTag") or "") != "DIRECT":
            continue
        if str(rule.get("port") or "") == "53" and "udp" in str(rule.get("network") or ""):
            return True
    return False


def _has_warp_default_rule(rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        if str(rule.get("outboundTag") or "") == "warp":
            net = str(rule.get("network") or "")
            if "tcp" in net and "udp" in net and not rule.get("domain") and not rule.get("ip"):
                return True
    return False


def apply_warp_safe_routing(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure WARP WireGuard can bootstrap when used as the default exit."""
    data = deepcopy(payload)
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
    if first_tag == "warp" and not _has_warp_default_rule(rules):
        rules.append(dict(WARP_DEFAULT_RULE))

    routing["rules"] = rules
    return data
