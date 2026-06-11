"""Normalize Xray inbounds before saving / restarting the core."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


NXPANEL_INBOUND_KIND = "nexusPanelKind"


def normalize_core_config_payload(payload: dict) -> dict:
    """Normalize Xray JSON before save/restart.

    - Ensures ``inbounds`` is always a list (may be empty).
    - Restores minimal ``outbounds`` / ``routing`` when missing or cleared.
    - Converts wireguard/amneziawg inbounds to valid Xray wireguard JSON.
    """
    data = deepcopy(payload)

    if not isinstance(data.get("inbounds"), list):
        data["inbounds"] = []

    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list) or not outbounds:
        data["outbounds"] = [
            {"protocol": "freedom", "tag": "DIRECT"},
            {"protocol": "blackhole", "tag": "BLOCK"},
        ]

    routing = data.get("routing")
    if not isinstance(routing, dict):
        data["routing"] = {"domainStrategy": "IPIfNonMatch", "rules": []}
    elif not isinstance(routing.get("rules"), list):
        routing["rules"] = []

    inbounds: List[Dict[str, Any]] = list(data.get("inbounds") or [])
    changed = False

    for inbound in inbounds:
        proto = str(inbound.get("protocol") or "").lower()
        if proto not in ("wireguard", "amneziawg"):
            continue

        settings = dict(inbound.get("settings") or {})
        is_amnezia = proto == "amneziawg" or settings.get(NXPANEL_INBOUND_KIND) == "amneziawg"

        inbound["protocol"] = "wireguard"
        inbound.pop("streamSettings", None)
        inbound.pop("sniffing", None)
        settings.pop("clients", None)

        if is_amnezia:
            settings[NXPANEL_INBOUND_KIND] = "amneziawg"

        secret = str(settings.get("secretKey") or "").strip()
        if not secret:
            from app.wireguard import generate_keypair

            secret, _pub = generate_keypair()
            settings["secretKey"] = secret
            changed = True

        try:
            mtu = int(settings.get("mtu") or 1420)
        except (TypeError, ValueError):
            mtu = 1420
        settings["mtu"] = mtu

        peers = settings.get("peers")
        if not isinstance(peers, list):
            settings["peers"] = []

        inbound["settings"] = settings
        changed = True

    data["inbounds"] = inbounds
    return data
