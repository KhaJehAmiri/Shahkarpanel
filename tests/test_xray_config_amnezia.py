"""Xray config: empty install template and AmneziaWG product inbounds."""
import json
from pathlib import Path

from app.models.proxy import ProxyTypes
from app.xray.config import XRayConfig
from app.xray.inbound_normalize import NXPANEL_INBOUND_KIND

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "xray_config.default.json"


def test_default_template_has_no_inbounds():
    data = json.loads(DEFAULT.read_text(encoding="utf-8"))
    assert data.get("inbounds") == []


def test_xray_amnezia_inbound_exposed_as_product():
    payload = {
        "inbounds": [
            {
                "tag": "AWG-Panel",
                "listen": "0.0.0.0",
                "port": 51820,
                "protocol": "wireguard",
                "settings": {
                    NXPANEL_INBOUND_KIND: "amneziawg",
                    "secretKey": "a" * 44,
                    "address": ["10.9.0.1/24"],
                    "peers": [],
                },
            },
            {
                "tag": "WG-Server-Only",
                "listen": "0.0.0.0",
                "port": 51821,
                "protocol": "wireguard",
                "settings": {"secretKey": "b" * 44, "address": ["10.9.1.1/24"], "peers": []},
            },
        ],
        "outbounds": [{"protocol": "freedom", "tag": "DIRECT"}],
    }
    cfg = XRayConfig(payload, api_port=8080)
    assert "amneziawg" in cfg.inbounds_by_protocol
    assert cfg.inbounds_by_protocol["amneziawg"][0]["tag"] == "AWG-Panel"
    assert "AWG-Panel" in cfg.inbounds_by_tag
    assert "WG-Server-Only" not in cfg.inbounds_by_tag
    assert cfg.product_inbounds_for_type(ProxyTypes.WireGuard)


def test_inject_xray_awg_peers_builds_peer_list():
    payload = {
        "inbounds": [
            {
                "tag": "AWG-1",
                "listen": "0.0.0.0",
                "port": 51820,
                "protocol": "wireguard",
                "settings": {
                    NXPANEL_INBOUND_KIND: "amneziawg",
                    "secretKey": "c" * 44,
                    "address": ["10.8.0.1/24"],
                    "peers": [],
                },
            },
        ],
        "outbounds": [{"protocol": "freedom", "tag": "DIRECT"}],
    }
    cfg = XRayConfig(payload, api_port=8080)
    out = cfg.copy()
    raw = out.get_inbound("AWG-1")
    grouped = {
        "wireguard": [
            [
                1,
                "alice",
                {
                    "public_key": "d" * 44,
                    "private_key": "e" * 44,
                    NXPANEL_INBOUND_KIND: "amneziawg",
                    "awg_address": "10.8.0.2/32",
                },
                [],
            ]
        ]
    }
    cfg._inject_xray_awg_peers(out, grouped)
    peers = raw["settings"]["peers"]
    assert len(peers) == 1
    assert peers[0]["publicKey"] == "d" * 44
    assert peers[0]["allowedIPs"] == ["10.8.0.2/32"]
