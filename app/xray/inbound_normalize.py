"""Normalize Xray inbounds before saving / restarting the core."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


def normalize_core_config_payload(payload: dict) -> dict:
    """Ensure wireguard/amneziawg inbounds are valid for Xray.

    - ``amneziawg`` is stored as ``wireguard`` in JSON (Xray has no amneziawg proto).
    - Auto-generate ``secretKey`` when empty (UI often leaves it blank).
    - Strip transport/sniffing fields that belong to proxy inbounds only.
    """
    data = deepcopy(payload)
    inbounds: List[Dict[str, Any]] = list(data.get("inbounds") or [])
    changed = False

    for inbound in inbounds:
        proto = str(inbound.get("protocol") or "").lower()
        if proto not in ("wireguard", "amneziawg"):
            continue

        inbound["protocol"] = "wireguard"
        inbound.pop("streamSettings", None)
        inbound.pop("sniffing", None)
        settings = dict(inbound.get("settings") or {})
        settings.pop("clients", None)

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

    if changed:
        data["inbounds"] = inbounds
    return data
