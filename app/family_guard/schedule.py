"""Schedule / daily-minutes evaluation for Family Guard."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from app.family_guard.policy import is_enabled, is_pause_active


def _tz(name: str):
    try:
        return ZoneInfo(name or "Asia/Tehran")
    except Exception:
        return ZoneInfo("Asia/Tehran")


def _parse_hm(value: str) -> Tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def within_windows(now_local: datetime, windows: list) -> bool:
    """True if now is inside any [start,end) window. Empty windows = always allowed."""
    if not windows:
        return True
    minutes = now_local.hour * 60 + now_local.minute
    for pair in windows:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        try:
            sh, sm = _parse_hm(str(pair[0]))
            eh, em = _parse_hm(str(pair[1]))
        except (TypeError, ValueError):
            continue
        start = sh * 60 + sm
        end = eh * 60 + em
        if start == end:
            continue
        if start < end:
            if start <= minutes < end:
                return True
        else:
            # overnight window e.g. 22:00–07:00
            if minutes >= start or minutes < end:
                return True
    return False


def evaluate_access(controls: Optional[dict]) -> Tuple[bool, Optional[str]]:
    """Return ``(allowed, reason)``. reason is set when blocked."""
    if not is_enabled(controls):
        return True, None
    if is_pause_active(controls):
        return True, None

    sched = (controls or {}).get("schedule") or {}
    tz = _tz(str(sched.get("tz") or "Asia/Tehran"))
    now_local = datetime.now(tz)
    iso_weekday = str(now_local.isoweekday())  # 1=Mon … 7=Sun
    windows = (sched.get("windows") or {}).get(iso_weekday) or []

    # If any day has windows configured, empty today means blocked for that day.
    any_windows = any(
        isinstance(v, list) and len(v) > 0
        for v in (sched.get("windows") or {}).values()
    )
    if any_windows and not within_windows(now_local, windows):
        return False, "outside_schedule"

    daily = sched.get("daily_minutes")
    if daily and int(daily) > 0:
        runtime = (controls or {}).get("runtime") or {}
        day_key = now_local.strftime("%Y-%m-%d")
        used = int(runtime.get("used_seconds") or 0)
        if runtime.get("day") == day_key and used >= int(daily) * 60:
            return False, "daily_limit"

    return True, None


def tick_usage(controls: dict, *, online: bool, interval_seconds: int = 60) -> dict:
    """Accumulate daily online seconds when the account is actively online."""
    out = dict(controls)
    runtime = dict(out.get("runtime") or {})
    sched = out.get("schedule") or {}
    tz = _tz(str(sched.get("tz") or "Asia/Tehran"))
    day_key = datetime.now(tz).strftime("%Y-%m-%d")
    if runtime.get("day") != day_key:
        runtime["day"] = day_key
        runtime["used_seconds"] = 0
    if online and is_enabled(out) and not is_pause_active(out):
        runtime["used_seconds"] = int(runtime.get("used_seconds") or 0) + max(
            0, int(interval_seconds)
        )
    out["runtime"] = runtime
    return out


def set_block_state(controls: dict, blocked: bool, reason: Optional[str]) -> dict:
    out = dict(controls)
    runtime = dict(out.get("runtime") or {})
    runtime["schedule_blocked"] = bool(blocked)
    runtime["block_reason"] = reason if blocked else None
    out["runtime"] = runtime
    return out


def pause_for(controls: dict, *, minutes: int = 60) -> dict:
    out = dict(controls)
    until = datetime.utcnow() + timedelta(minutes=max(1, int(minutes)))
    out["pause_until"] = int(until.timestamp())
    out = set_block_state(out, False, None)
    return out
