"""Tests for wireguard/amneziawg inbound normalization."""
from app.xray.inbound_normalize import normalize_core_config_payload


def _minimal_payload(inbound: dict) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [inbound],
        "outbounds": [
            {"protocol": "freedom", "tag": "DIRECT"},
            {"protocol": "blackhole", "tag": "BLOCK"},
        ],
        "routing": {"rules": []},
    }


def test_normalize_amneziawg_generates_secret_key():
    raw = _minimal_payload(
        {
            "tag": "AmneziaWG",
            "listen": "0.0.0.0",
            "port": 51821,
            "protocol": "amneziawg",
            "settings": {"secretKey": "", "mtu": 1420, "peers": []},
            "streamSettings": {"network": "tcp", "security": "reality"},
        }
    )
    out = normalize_core_config_payload(raw)
    ib = out["inbounds"][0]
    assert ib["protocol"] == "wireguard"
    assert ib["settings"]["secretKey"]
    assert ib["settings"]["nexusPanelKind"] == "amneziawg"
    assert "streamSettings" not in ib


def test_normalize_amneziawg_keeps_ui_marker():
    raw = _minimal_payload(
        {
            "tag": "s",
            "listen": "0.0.0.0",
            "port": 443,
            "protocol": "amneziawg",
            "settings": {"secretKey": "existingKey==", "mtu": 1420, "peers": []},
        }
    )
    out = normalize_core_config_payload(raw)
    ib = out["inbounds"][0]
    assert ib["protocol"] == "wireguard"
    assert ib["settings"]["nexusPanelKind"] == "amneziawg"


def test_normalize_wireguard_keeps_existing_secret():
    raw = _minimal_payload(
        {
            "tag": "WG",
            "listen": "0.0.0.0",
            "port": 51820,
            "protocol": "wireguard",
            "settings": {"secretKey": "existingKey==", "mtu": 1420, "peers": []},
        }
    )
    out = normalize_core_config_payload(raw)
    assert out["inbounds"][0]["settings"]["secretKey"] == "existingKey=="
    assert "nexusPanelKind" not in out["inbounds"][0]["settings"]
