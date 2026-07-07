"""Outbound preset library (SOCKS/HTTP pools + balancers)."""
from __future__ import annotations

OUTBOUND_PRESETS: dict[str, dict] = {
    "socks-pool-failover": {
        "label": "SOCKS pool with leastPing balancer",
        "description": "Health-aware failover across multiple SOCKS5 upstreams (observatory + leastPing).",
        "protocol": "socks",
        "default_balancer_tag": "socks-pool",
        "default_tag_prefix": "socks-up",
        "default_strategy": "leastPing",
        "strategies": ["leastPing", "random", "roundRobin"],
        "outbounds": [
            {
                "tag": "socks-up-1",
                "protocol": "socks",
                "settings": {"servers": [{"address": "127.0.0.1", "port": 1080}]},
            },
            {
                "tag": "socks-up-2",
                "protocol": "socks",
                "settings": {"servers": [{"address": "127.0.0.1", "port": 1081}]},
            },
        ],
        "routing": [],
        "balancers": [
            {
                "tag": "socks-pool",
                "selector": ["socks-up-1", "socks-up-2"],
                "strategy": {"type": "leastPing"},
            }
        ],
    },
    "http-pool-random": {
        "label": "HTTP proxy pool (random)",
        "description": "Random selection across HTTP upstream proxies.",
        "protocol": "http",
        "default_balancer_tag": "http-pool",
        "default_tag_prefix": "http-up",
        "default_strategy": "random",
        "strategies": ["random", "roundRobin", "leastPing"],
        "outbounds": [
            {
                "tag": "http-up-1",
                "protocol": "http",
                "settings": {"servers": [{"address": "127.0.0.1", "port": 8080}]},
            },
        ],
        "routing": [],
        "balancers": [
            {
                "tag": "http-pool",
                "selector": ["http-up-1"],
                "strategy": {"type": "random"},
            }
        ],
    },
}
