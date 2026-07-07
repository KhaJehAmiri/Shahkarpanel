"""Built-in Xray routing rule packs (geo/block/adblock presets)."""
from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import urlparse

import yaml

SING_GEOSITE_RULE_SET_BASE = (
    "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set"
)

ROUTING_PRESETS: dict[str, dict] = {
    "direct-local": {
        "label": "Direct LAN & private ranges",
        "rules": [
            {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
            {"type": "field", "domain": ["geosite:category-ir"], "outboundTag": "direct"},
        ],
    },
    "block-ads": {
        "label": "Block ads (geosite)",
        "rules": [
            {"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block"},
        ],
    },
    "proxy-foreign": {
        "label": "Proxy non-IR traffic",
        "rules": [
            {"type": "field", "domain": ["geosite:geolocation-!cn"], "outboundTag": "proxy"},
            {"type": "field", "ip": ["geoip:!cn"], "outboundTag": "proxy"},
        ],
    },
}


DNS_PRESETS: dict[str, dict] = {
    "split-local": {
        "label": "Split-horizon: IR/CN local DNS",
        "policy": {
            "servers": [
                {
                    "address": "223.5.5.5",
                    "domains": ["geosite:category-ir", "geosite:cn"],
                    "skipFallback": True,
                },
                "8.8.8.8",
            ],
        },
    },
    "split-doh": {
        "label": "Split-horizon: IR local + DoH fallback",
        "policy": {
            "servers": [
                {
                    "address": "223.5.5.5",
                    "domains": ["geosite:category-ir"],
                    "skipFallback": True,
                },
                "https://dns.google/dns-query",
            ],
        },
    },
    "fake-dns": {
        "label": "Fake DNS (sniffing)",
        "policy": {
            "servers": ["8.8.8.8"],
            "fakeDns": {"enabled": True},
        },
    },
    "fake-dns-split-ir": {
        "label": "Fake DNS + IR split horizon",
        "policy": {
            "servers": [
                {
                    "address": "223.5.5.5",
                    "domains": ["geosite:category-ir"],
                    "skipFallback": True,
                },
                "https://1.1.1.1/dns-query",
            ],
            "fakeDns": {"enabled": True},
        },
    },
}


def resolve_dns_policy(dns_policy: Optional[dict]) -> Optional[dict]:
    """Expand ``{"preset": "id"}`` into the preset DNS fragment."""
    if not dns_policy:
        return None
    preset_id = dns_policy.get("preset")
    if preset_id:
        spec = DNS_PRESETS.get(str(preset_id))
        if spec:
            return dict(spec.get("policy") or {})
    return dict(dns_policy)


def _merge_dns(base: dict, patch: dict) -> dict:
    """Shallow merge with nested dict support (e.g. fakeDns)."""
    out = dict(base)
    for key, value in patch.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def apply_routing_preset_to_json(config_text: str, preset_id: Optional[str]) -> str:
    if not preset_id or preset_id not in ROUTING_PRESETS:
        return config_text
    rules = ROUTING_PRESETS[preset_id].get("rules") or []
    if not rules:
        return config_text
    try:
        parsed = json.loads(config_text)
    except (json.JSONDecodeError, TypeError):
        return config_text
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                routing = item.setdefault("routing", {})
                if isinstance(routing, dict):
                    routing.setdefault("rules", [])
                    if isinstance(routing["rules"], list):
                        routing["rules"] = rules + routing["rules"]
    elif isinstance(parsed, dict):
        routing = parsed.setdefault("routing", {})
        if isinstance(routing, dict):
            routing.setdefault("rules", [])
            if isinstance(routing["rules"], list):
                routing["rules"] = rules + routing["rules"]
    return json.dumps(parsed, indent=2)


def apply_dns_policy_to_json(config_text: str, dns_policy: Optional[dict]) -> str:
    resolved = resolve_dns_policy(dns_policy)
    if not resolved:
        return config_text
    try:
        parsed = json.loads(config_text)
    except (json.JSONDecodeError, TypeError):
        return config_text
    targets = parsed if isinstance(parsed, list) else [parsed]
    for item in targets:
        if isinstance(item, dict):
            dns = item.setdefault("dns", {})
            if isinstance(dns, dict):
                merged = _merge_dns(dns, resolved)
                item["dns"] = merged
    return json.dumps(parsed, indent=2)


def _parse_xray_dns_server(server: Any) -> tuple[str, str, list[str] | None]:
    """Return ``(address, proto, geosite_domains)`` where proto is ``udp`` or ``doh``."""
    if isinstance(server, str):
        if server.startswith("https://"):
            return server, "doh", None
        return server, "udp", None
    if isinstance(server, dict):
        addr = str(server.get("address") or "")
        domains = server.get("domains")
        geos = [str(d) for d in domains] if isinstance(domains, list) else None
        if addr.startswith("https://"):
            return addr, "doh", geos
        return addr, "udp", geos
    return "", "udp", None


def _parse_doh_host_path(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path or "/dns-query"
    port = parsed.port or 443
    return host, path, port


def _geosite_to_singbox_rule_set_tag(geosite: str) -> str:
    name = geosite.split(":", 1)[-1]
    return f"geosite-{name}"


def _singbox_remote_rule_set(tag: str) -> dict:
    return {
        "tag": tag,
        "type": "remote",
        "format": "binary",
        "url": f"{SING_GEOSITE_RULE_SET_BASE}/{tag}.srs",
        "download_detour": "direct",
    }


def _singbox_udp_server(tag: str, address: str, *, detour: str | None = None) -> dict:
    entry: dict = {"tag": tag, "type": "udp", "server": address}
    if detour:
        entry["detour"] = detour
    return entry


def _singbox_doh_server(tag: str, doh_url: str, *, detour: str = "proxy") -> dict:
    host, path, port = _parse_doh_host_path(doh_url)
    return {
        "tag": tag,
        "type": "https",
        "server": host,
        "server_port": port,
        "path": path,
        "domain_resolver": "dns-local",
        "detour": detour,
    }


def build_clash_dns(resolved: dict) -> dict:
    """Map an Xray-style DNS policy to mihomo / Clash Meta ``dns`` block."""
    servers = resolved.get("servers") or []
    fake_dns = bool((resolved.get("fakeDns") or {}).get("enabled"))

    nameserver: list[str] = []
    fallback: list[str] = []
    policy: dict[str, str] = {}

    for server in servers:
        addr, proto, domains = _parse_xray_dns_server(server)
        if not addr:
            continue
        if domains:
            target = addr if proto == "udp" else addr
            for domain in domains:
                policy[domain] = target
            if proto == "udp" and addr not in nameserver:
                nameserver.append(addr)
        elif proto == "doh":
            if addr not in fallback:
                fallback.append(addr)
        elif addr not in nameserver:
            nameserver.append(addr)

    if not nameserver:
        nameserver = ["223.5.5.5"]
    if not fallback:
        fallback = list(nameserver)

    dns: dict = {
        "enable": True,
        "ipv6": False,
        "enhanced-mode": "fake-ip" if fake_dns else "redir-host",
        "default-nameserver": ["223.5.5.5", "119.29.29.29"],
        "nameserver": nameserver,
        "fallback": fallback,
    }
    if fake_dns:
        dns["fake-ip-range"] = "198.18.0.0/16"
    if policy:
        dns["nameserver-policy"] = policy
    return dns


def build_singbox_dns(resolved: dict) -> tuple[dict, list[dict]]:
    """Map an Xray-style DNS policy to sing-box ``dns`` + optional ``rule_set`` entries."""
    servers = resolved.get("servers") or []
    fake_dns = bool((resolved.get("fakeDns") or {}).get("enabled"))

    sb_servers: list[dict] = [{"tag": "dns-local", "type": "local"}]
    rules: list[dict] = [{"domain": "localhost", "server": "dns-local"}]
    rule_sets: list[dict] = []
    final = "dns-remote"
    remote_idx = 0

    if fake_dns:
        sb_servers.append(
            {
                "tag": "dns-fake",
                "type": "fakeip",
                "inet4_range": "198.18.0.0/15",
            }
        )

    for server in servers:
        addr, proto, domains = _parse_xray_dns_server(server)
        if not addr:
            continue

        if domains:
            tag = f"dns-split-{addr.replace('.', '-')}"
            if proto == "doh":
                sb_servers.append(_singbox_doh_server(tag, addr, detour="direct"))
            else:
                sb_servers.append(_singbox_udp_server(tag, addr))
            for domain in domains:
                if domain.startswith("geosite:"):
                    rs_tag = _geosite_to_singbox_rule_set_tag(domain)
                    rule_sets.append(_singbox_remote_rule_set(rs_tag))
                    rules.append({"rule_set": rs_tag, "server": tag})
                elif domain.startswith("domain:"):
                    rules.append({"domain_suffix": [domain.split(":", 1)[1]], "server": tag})
                else:
                    rules.append({"domain_suffix": [f".{domain}"], "server": tag})
            continue

        remote_idx += 1
        tag = "dns-remote" if remote_idx == 1 else f"dns-remote-{remote_idx}"
        if remote_idx == 1:
            final = tag
        if proto == "doh":
            sb_servers.append(_singbox_doh_server(tag, addr))
        else:
            sb_servers.append(_singbox_udp_server(tag, addr, detour="proxy"))

    if fake_dns:
        rules.append({"query_type": ["A", "AAAA"], "server": "dns-fake"})

    dns = {
        "servers": sb_servers,
        "rules": rules,
        "final": final,
        "strategy": "prefer_ipv4",
    }
    return dns, rule_sets


def _merge_singbox_rule_sets(existing: list, additions: list[dict]) -> list:
    by_tag = {item.get("tag"): item for item in existing if isinstance(item, dict) and item.get("tag")}
    for item in additions:
        tag = item.get("tag")
        if tag and tag not in by_tag:
            by_tag[tag] = item
    return list(by_tag.values())


def apply_dns_policy_to_singbox(config_text: str, dns_policy: Optional[dict]) -> str:
    resolved = resolve_dns_policy(dns_policy)
    if not resolved:
        return config_text
    try:
        parsed = json.loads(config_text)
    except (json.JSONDecodeError, TypeError):
        return config_text
    if not isinstance(parsed, dict):
        return config_text

    dns_config, rule_sets = build_singbox_dns(resolved)
    parsed["dns"] = dns_config
    if rule_sets:
        parsed["rule_set"] = _merge_singbox_rule_sets(parsed.get("rule_set") or [], rule_sets)
    return json.dumps(parsed, indent=4)


def apply_dns_policy_to_clash(config_text: str, dns_policy: Optional[dict]) -> str:
    resolved = resolve_dns_policy(dns_policy)
    if not resolved:
        return config_text
    try:
        parsed = yaml.safe_load(config_text)
    except (yaml.YAMLError, TypeError):
        return config_text
    if not isinstance(parsed, dict):
        return config_text

    parsed["dns"] = build_clash_dns(resolved)
    return yaml.dump(parsed, sort_keys=False, allow_unicode=True)
