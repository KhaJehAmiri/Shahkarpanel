"""First-class Xray inbound presets (TUIC/AnyTLS via sing-box bridge stubs)."""
from __future__ import annotations

INBOUND_PRESETS: dict[str, dict] = {
    "tuic-inbound": {
        "label": "TUIC (sing-box node)",
        "note": "QUIC inbound on a connected node via sing-box — not an Xray protocol.",
        "deploy": "singbox",
        "protocol": "tuic",
        "default_port": 44334,
        "default_congestion_control": "bbr",
        "transport": "quic",
        "inbound": None,
    },
    "anytls-inbound": {
        "label": "AnyTLS (sing-box node)",
        "note": "AnyTLS inbound on a connected node via sing-box.",
        "deploy": "singbox",
        "protocol": "anytls",
        "default_port": 44335,
        "transport": "tcp",
        "inbound": None,
    },
    "vless-reality-tcp": {
        "label": "VLESS REALITY TCP",
        "inbound": {
            "tag": "VLESS-REALITY-TCP",
            "listen": "0.0.0.0",
            "port": 443,
            "protocol": "vless",
            "settings": {"clients": [], "decryption": "none"},
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {"show": False, "target": "www.cloudflare.com:443"},
            },
        },
    },
}
