"""Country-pair tunnel presets and multi-hop templates."""
from __future__ import annotations

TUNNEL_TEMPLATES: dict[str, dict] = {
    "iran-relay-exit": {
        "label": "Iran relay → foreign exit (Reality)",
        "relay_region": "IR",
        "exit_region": "DE",
        "transport": "reality",
        "hops": 2,
        "params": {},
    },
    "iran-relay-exit-ws": {
        "label": "Iran relay → foreign exit (WebSocket+TLS)",
        "relay_region": "IR",
        "exit_region": "NL",
        "transport": "ws",
        "hops": 2,
        "params": {"path": "/tunnel-ws"},
    },
    "multihop-2": {
        "label": "Two-hop chain (relay → exit)",
        "transport": "reality",
        "hops": 2,
        "params": {},
    },
    "multihop-3": {
        "label": "Three-hop chain (relay → transit → exit)",
        "transport": "reality",
        "hops": 3,
        "params": {},
    },
    "quic-hysteria-stub": {
        "label": "VLESS/QUIC hop (Hysteria-like)",
        "transport": "quic",
        "hops": 2,
        "params": {"security": "tls", "sni": "www.cloudflare.com", "alpn": "h3", "header_type": "none"},
    },
    "tuic-tunnel-stub": {
        "label": "TUIC hop (sing-box stub)",
        "transport": "tuic",
        "hops": 2,
        "params": {"congestion_control": "bbr", "sni": "www.cloudflare.com", "alpn": "h3"},
    },
    "hysteria2-tunnel-stub": {
        "label": "Hysteria2 hop (sing-box stub)",
        "transport": "hysteria2",
        "hops": 2,
        "params": {"sni": "www.cloudflare.com", "up_mbps": 100, "down_mbps": 200},
    },
}


def get_template(template_id: str) -> dict:
    """Return a template spec or raise ``KeyError``."""
    if template_id not in TUNNEL_TEMPLATES:
        raise KeyError(template_id)
    return TUNNEL_TEMPLATES[template_id]


def template_hops(spec: dict) -> int:
    """Number of node endpoints in the chain (2 = relay+exit, 3 = +transit)."""
    return int(spec.get("hops", 2))


def requires_intermediate(spec: dict) -> bool:
    return template_hops(spec) >= 3


def is_iran_region(region: str | None) -> bool:
    r = (region or "").strip().lower()
    return r in ("ir", "iran", "domestic") or r.startswith("ir-")


def region_matches(preset: str | None, node_region: str | None) -> bool:
    """True when a node's ``region`` satisfies a template region preset (e.g. IR, DE)."""
    if not preset or not node_region:
        return False
    p = preset.strip().upper()
    if p == "IR":
        return is_iran_region(node_region)
    r = node_region.strip().upper()
    return r == p or r.startswith(f"{p}-")


def template_relay_region(spec: dict) -> str | None:
    return spec.get("relay_region")


def template_exit_region(spec: dict) -> str | None:
    return spec.get("exit_region")


def is_iran_pair_template(spec: dict) -> bool:
    return bool(template_relay_region(spec))


def serialize_template(template_id: str, spec: dict) -> dict:
    """API-facing template payload with normalized metadata."""
    out = {**spec, "id": template_id, "hops": template_hops(spec)}
    if is_iran_pair_template(spec):
        out["category"] = "iran-pair"
    elif template_id.startswith("multihop"):
        out["category"] = "multihop"
    else:
        out["category"] = "general"
    return out


def iran_pair_templates() -> dict[str, dict]:
    return {
        tid: serialize_template(tid, spec)
        for tid, spec in TUNNEL_TEMPLATES.items()
        if is_iran_pair_template(spec)
    }
