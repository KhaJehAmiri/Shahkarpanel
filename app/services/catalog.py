"""Central service catalog — define each product protocol once on the master.

Nodes only enable/disable service slugs; ``materialize`` writes the legacy
``node_singbox`` / ``node_wireguard`` rows the node agent already understands.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# slug → definition (seeded into ``panel_services`` on migration)
SERVICE_SEEDS: List[Dict[str, Any]] = [
    {
        "slug": "xray",
        "display_name": "Xray (all product inbounds)",
        "engine": "xray",
        "protocol": "xray",
        "config": {"mode": "all_inbounds"},
        "sort_order": 10,
    },
    {
        "slug": "wireguard-plain",
        "display_name": "WireGuard",
        "engine": "wireguard",
        "protocol": "wireguard",
        "config": {"listen_port": 51820, "subnet": "10.10.0.0/24", "mtu": 1420},
        "sort_order": 20,
    },
    {
        "slug": "amneziawg",
        "display_name": "AmneziaWG",
        "engine": "wireguard",
        "protocol": "amneziawg",
        "config": {"awg_listen_port": 51821, "awg_subnet": "10.11.0.0/24", "mtu": 1420},
        "sort_order": 21,
    },
    {
        "slug": "hysteria2",
        "display_name": "Hysteria2",
        "engine": "singbox",
        "protocol": "hysteria2",
        "config": {"port": 44333, "up_mbps": None, "down_mbps": None},
        "sort_order": 30,
    },
    {
        "slug": "tuic",
        "display_name": "TUIC",
        "engine": "singbox",
        "protocol": "tuic",
        "config": {"port": 44334, "congestion_control": "bbr"},
        "sort_order": 31,
    },
    {
        "slug": "anytls",
        "display_name": "AnyTLS",
        "engine": "singbox",
        "protocol": "anytls",
        "config": {"port": 44335},
        "sort_order": 32,
    },
]

SINGBOX_SLUGS = frozenset({"hysteria2", "tuic", "anytls"})
WIREGUARD_SLUGS = frozenset({"wireguard-plain", "amneziawg"})


def service_port(config: dict, overrides: Optional[dict], key: str = "port") -> Optional[int]:
    if overrides and overrides.get(key) is not None:
        return int(overrides[key])
    val = (config or {}).get(key)
    return int(val) if val is not None else None


def merge_overrides(base: dict, overrides: Optional[dict]) -> dict:
    out = dict(base or {})
    if overrides:
        out.update({k: v for k, v in overrides.items() if v is not None})
    return out
