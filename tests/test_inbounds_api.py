"""GET /inbounds must expose panel-master AmneziaWG listeners."""
from pydantic import TypeAdapter

from app.models.proxy import ProxyInbound, ProxyTypes
from app.xray.config import XRayConfig
from app.xray.inbound_normalize import NXPANEL_INBOUND_KIND


def test_amneziawg_bucket_serializes_for_api():
    payload = {
        "inbounds": [
            {
                "tag": "AWG-Master",
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
        ],
        "outbounds": [{"protocol": "freedom", "tag": "DIRECT"}],
    }
    cfg = XRayConfig(payload, api_port=8080)
    api_payload = {key: list(items) for key, items in cfg.inbounds_by_protocol.items()}
    assert "amneziawg" in api_payload
    ta = TypeAdapter(dict[str, list[ProxyInbound]])
    parsed = ta.validate_python({"wireguard": api_payload["amneziawg"]})
    assert parsed["wireguard"][0].protocol == ProxyTypes.WireGuard


def test_amneziawg_detected_by_inbound_tag():
    payload = {
        "inbounds": [
            {
                "tag": "AmneziaWG-Master",
                "listen": "0.0.0.0",
                "port": 51821,
                "protocol": "wireguard",
                "settings": {"secretKey": "b" * 44, "address": ["10.10.0.1/24"], "peers": []},
            },
        ],
        "outbounds": [{"protocol": "freedom", "tag": "DIRECT"}],
    }
    cfg = XRayConfig(payload, api_port=8080)
    assert "amneziawg" in cfg.inbounds_by_protocol
