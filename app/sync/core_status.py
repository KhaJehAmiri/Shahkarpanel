"""Local Xray status for Overview ticks.

The 250ms WebSocket tick must never ``from app import xray`` — that import
loads the 27k-user config and deadlocks with ``start_core()``. The core
lifecycle writes this cache; ticks only read it.
"""
from __future__ import annotations

import time
from typing import Optional

_started: bool = False
_version: str = ""
_started_at: Optional[float] = None


def note_core(started: bool, version: str = "", started_at: Optional[float] = None) -> None:
    global _started, _version, _started_at
    _started = bool(started)
    if version:
        _version = str(version)
    if not started:
        _started_at = None
        return
    _started_at = float(started_at) if started_at else time.time()


def snapshot() -> tuple[int, int, bool, str]:
    """Return (xray_uptime, node_uptime, started, version)."""
    started = _started
    version = _version
    started_at = _started_at
    uptime = 0
    if started and started_at:
        uptime = max(0, int(time.time() - started_at))
    return uptime, 0, started, version
