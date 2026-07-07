"""Decide whether a saved Xray master config can be applied without a core restart.

When inbound *structure* (listen/port/protocol/stream/tls — not DB user rows)
is unchanged, the live listeners stay valid. We can persist the new JSON and
reconcile users through the handler gRPC API instead of restarting Xray and
dropping every session (3x-ui-style ``AlterInbound`` behaviour).
"""
from __future__ import annotations

import copy
import json
from typing import Any

from app import xray

_DYNAMIC_INBOUND_SETTINGS_KEYS = frozenset(
    {"clients", "users", "peers", "accounts", "decryption"}
)


def _strip_dynamic_inbound_fields(inbound: dict[str, Any]) -> dict[str, Any]:
    ib = copy.deepcopy(inbound)
    settings = ib.get("settings")
    if isinstance(settings, dict):
        for key in _DYNAMIC_INBOUND_SETTINGS_KEYS:
            settings.pop(key, None)
    return ib


def inbounds_structure_signature(config: dict[str, Any]) -> str:
    """Stable fingerprint of listener-defining inbound fields (ignores DB users)."""
    parts: list[str] = []
    for ib in sorted(config.get("inbounds") or [], key=lambda x: str(x.get("tag") or "")):
        if not isinstance(ib, dict):
            continue
        parts.append(json.dumps(_strip_dynamic_inbound_fields(ib), sort_keys=True, ensure_ascii=True))
    return "\n".join(parts)


def inbounds_structure_changed(old_startup: dict[str, Any], new_startup: dict[str, Any]) -> bool:
    return inbounds_structure_signature(old_startup) != inbounds_structure_signature(new_startup)


def can_hot_apply_core_config(
    old_startup: dict[str, Any],
    new_startup: dict[str, Any],
    *,
    core_started: bool | None = None,
) -> bool:
    """True when the running core can keep existing sessions after a config save."""
    if core_started is None:
        core_started = bool(getattr(xray.core, "started", False))
    if not core_started or getattr(xray.core, "restarting", False):
        return False
    return not inbounds_structure_changed(old_startup, new_startup)
