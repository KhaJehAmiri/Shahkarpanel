"""Normalize / sanitize Family Guard JSON stored on ``User.family_controls``."""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.family_guard.services import SERVICE_CATALOG

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]+(\.[a-z0-9-]+)+$",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def default_controls() -> Dict[str, Any]:
    return {
        "enabled": False,
        "block_adult": False,
        "block_ads": False,
        "services": [],
        "custom_domains": [],
        "schedule": {
            "tz": "Asia/Tehran",
            "windows": {str(i): [] for i in range(1, 8)},
            "daily_minutes": None,
        },
        "pause_until": None,
        "runtime": {
            "day": None,
            "used_seconds": 0,
            "schedule_blocked": False,
            "block_reason": None,
        },
    }


def _parse_domain(raw: str) -> Optional[str]:
    s = (raw or "").strip().lower()
    if not s:
        return None
    s = s.replace("https://", "").replace("http://", "")
    s = s.split("/")[0].split("?")[0].split("#")[0]
    if s.startswith("*."):
        s = s[2:]
    s = s.lstrip(".")
    if s.startswith("www."):
        s = s[4:]
    if not _DOMAIN_RE.match(s):
        return None
    return s


def _normalize_windows(raw: Any) -> Dict[str, List[List[str]]]:
    out: Dict[str, List[List[str]]] = {str(i): [] for i in range(1, 8)}
    if not isinstance(raw, dict):
        return out
    for key, windows in raw.items():
        try:
            day = int(key)
        except (TypeError, ValueError):
            continue
        if day < 1 or day > 7:
            continue
        cleaned: List[List[str]] = []
        if not isinstance(windows, list):
            out[str(day)] = cleaned
            continue
        for pair in windows:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            start, end = str(pair[0]).strip(), str(pair[1]).strip()
            if not _TIME_RE.match(start) or not _TIME_RE.match(end):
                continue
            cleaned.append([start, end])
        out[str(day)] = cleaned
    return out


def merge_controls(existing: Optional[dict], patch: Optional[dict]) -> Dict[str, Any]:
    """Merge a portal PUT body onto existing controls (keeps pin_hash/runtime)."""
    base = default_controls()
    if isinstance(existing, dict):
        base = {**base, **deepcopy(existing)}
        if isinstance(existing.get("schedule"), dict):
            base["schedule"] = {
                **default_controls()["schedule"],
                **deepcopy(existing["schedule"]),
            }
        if isinstance(existing.get("runtime"), dict):
            base["runtime"] = {
                **default_controls()["runtime"],
                **deepcopy(existing["runtime"]),
            }

    if not isinstance(patch, dict):
        return base

    if "enabled" in patch:
        base["enabled"] = bool(patch["enabled"])
    if "block_adult" in patch:
        base["block_adult"] = bool(patch["block_adult"])
    if "block_ads" in patch:
        base["block_ads"] = bool(patch["block_ads"])

    if "services" in patch and isinstance(patch["services"], list):
        services: List[str] = []
        for sid in patch["services"]:
            key = str(sid).strip().lower()
            if key in SERVICE_CATALOG and key not in services:
                services.append(key)
        base["services"] = services

    if "custom_domains" in patch and isinstance(patch["custom_domains"], list):
        domains: List[str] = []
        seen: set[str] = set()
        for raw in patch["custom_domains"]:
            d = _parse_domain(str(raw))
            if d and d not in seen:
                seen.add(d)
                domains.append(d)
            if len(domains) >= 500:
                break
        base["custom_domains"] = domains

    if "schedule" in patch and isinstance(patch["schedule"], dict):
        sched = dict(base.get("schedule") or {})
        src = patch["schedule"]
        if "tz" in src and isinstance(src["tz"], str) and src["tz"].strip():
            sched["tz"] = src["tz"].strip()[:64]
        if "windows" in src:
            sched["windows"] = _normalize_windows(src["windows"])
        if "daily_minutes" in src:
            dm = src["daily_minutes"]
            if dm is None or dm == "" or int(dm or 0) <= 0:
                sched["daily_minutes"] = None
            else:
                sched["daily_minutes"] = min(24 * 60, max(1, int(dm)))
        base["schedule"] = sched

    if "pause_until" in patch:
        pu = patch["pause_until"]
        if pu in (None, "", 0, False):
            base["pause_until"] = None
        else:
            try:
                if isinstance(pu, (int, float)):
                    base["pause_until"] = int(pu)
                else:
                    # ISO datetime → epoch
                    dt = datetime.fromisoformat(str(pu).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    base["pause_until"] = int(dt.timestamp())
            except (TypeError, ValueError):
                pass

    return base


def public_controls(controls: Optional[dict]) -> Dict[str, Any]:
    """API-safe view (no pin_hash)."""
    data = merge_controls(controls, None)
    data.pop("pin_hash", None)
    runtime = dict(data.get("runtime") or {})
    data["runtime"] = {
        "day": runtime.get("day"),
        "used_seconds": int(runtime.get("used_seconds") or 0),
        "schedule_blocked": bool(runtime.get("schedule_blocked")),
        "block_reason": runtime.get("block_reason"),
    }
    data["pin_set"] = bool((controls or {}).get("pin_hash"))
    data["pause_active"] = is_pause_active(controls)
    return data


def is_pause_active(controls: Optional[dict]) -> bool:
    if not isinstance(controls, dict):
        return False
    until = controls.get("pause_until")
    if not until:
        return False
    try:
        return int(until) > int(datetime.utcnow().timestamp())
    except (TypeError, ValueError):
        return False


def is_enabled(controls: Optional[dict]) -> bool:
    return bool(isinstance(controls, dict) and controls.get("enabled"))
