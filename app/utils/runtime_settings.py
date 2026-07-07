"""Persisted panel runtime settings (override env defaults without restart)."""
from __future__ import annotations

import json
import os
from typing import Any

_SETTINGS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "panel_runtime.json")
)


def _load() -> dict[str, Any]:
    if not os.path.isfile(_SETTINGS_PATH):
        return {}
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_SETTINGS_PATH), mode=0o700, exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get(key: str, default: Any = None) -> Any:
    return _load().get(key, default)


def set_value(key: str, value: Any) -> None:
    data = _load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    _save(data)


def backup_interval_hours() -> int:
    from config import BACKUP_INTERVAL_HOURS

    val = get("backup_interval_hours")
    if val is None:
        return int(BACKUP_INTERVAL_HOURS)
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return int(BACKUP_INTERVAL_HOURS)


def xray_auto_upgrade_config() -> dict[str, Any]:
    from config import (
        XRAY_AUTO_UPGRADE_ENABLED,
        XRAY_AUTO_UPGRADE_INCLUDE_PRERELEASE,
        XRAY_AUTO_UPGRADE_INTERVAL,
    )

    data = _load()
    return {
        "enabled": bool(data.get("xray_auto_upgrade_enabled", XRAY_AUTO_UPGRADE_ENABLED)),
        "interval_seconds": int(data.get("xray_auto_upgrade_interval", XRAY_AUTO_UPGRADE_INTERVAL)),
        "include_prerelease": bool(
            data.get("xray_auto_upgrade_include_prerelease", XRAY_AUTO_UPGRADE_INCLUDE_PRERELEASE)
        ),
    }
