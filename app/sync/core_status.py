"""Local Xray status for Overview ticks.

The 250ms WebSocket tick must never ``from app import xray`` — that import
loads the 27k-user config and deadlocks with ``start_core()``. The core
lifecycle writes this cache; ticks only read it.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Optional

_noted: bool = False
_started: bool = False
_version: str = ""
_started_at: Optional[float] = None


def note_core(started: bool, version: str = "", started_at: Optional[float] = None) -> None:
    global _noted, _started, _version, _started_at
    _noted = True
    _started = bool(started)
    if version:
        _version = str(version)
    if not started:
        _started_at = None
        return
    _started_at = float(started_at) if started_at else time.time()


def _stdin_xray_pid() -> Optional[int]:
    paths = [
        (os.environ.get("XRAY_EXECUTABLE_PATH") or "").strip(),
        "/var/lib/nexuspanel/bin/xray",
        "/var/lib/shahkar/bin/xray",
    ]
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", f"^{re.escape(path)} run -config stdin:"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            continue
        for line in out.splitlines():
            if line.strip().isdigit():
                return int(line.strip())
    return None


def _adopt_running_process() -> bool:
    """If Xray is up but this process never called note_core, use /proc start time."""
    pid = _stdin_xray_pid()
    if not pid:
        return False
    try:
        started_at = os.stat(f"/proc/{pid}").st_ctime
    except OSError:
        started_at = time.time()
    note_core(True, _version, started_at)
    return True


def snapshot() -> tuple[int, int, bool, str]:
    """Return (xray_uptime, node_uptime, started, version)."""
    if not _noted:
        _adopt_running_process()
    started = _started
    version = _version
    started_at = _started_at
    uptime = 0
    if started and started_at:
        uptime = max(0, int(time.time() - started_at))
    return uptime, 0, started, version
