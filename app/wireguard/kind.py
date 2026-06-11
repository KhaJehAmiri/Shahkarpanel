"""WireGuard / AmneziaWG user intent markers (panel-only, not sent to nodes)."""
from __future__ import annotations

from typing import Dict, List

NXPANEL_WG_KIND = "nexusPanelKind"


def wg_settings_kind(settings: Dict) -> str | None:
    kind = settings.get(NXPANEL_WG_KIND)
    if kind in ("wireguard", "amneziawg", "both"):
        return kind
    return None


def user_wg_stack_labels(settings: Dict) -> List[str]:
    """Labels for UI badges: wireguard, amneziawg, or both."""
    kind = wg_settings_kind(settings)
    if kind == "both":
        return ["wireguard", "amneziawg"]
    if kind == "amneziawg":
        return ["amneziawg"]
    if kind == "wireguard":
        return ["wireguard"]

    awg = bool(settings.get("awg_address"))
    plain = bool(settings.get("address"))
    if awg and plain:
        return ["wireguard", "amneziawg"]
    if awg:
        return ["amneziawg"]
    return ["wireguard"]


def wg_wants_plain_address(settings: Dict) -> bool:
    return "wireguard" in user_wg_stack_labels(settings)


def wg_wants_awg_address(settings: Dict) -> bool:
    return "amneziawg" in user_wg_stack_labels(settings)


def wg_kind_from_template_tags(tags: List[str]) -> str | None:
    has_plain = "__native:wireguard" in tags
    has_awg = "__native:amneziawg" in tags
    if has_plain and has_awg:
        return "both"
    if has_awg:
        return "amneziawg"
    if has_plain:
        return "wireguard"
    return None
