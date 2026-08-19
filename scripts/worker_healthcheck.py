#!/usr/bin/env python3
"""Compose healthcheck for the control-plane worker (file or Redis heartbeat)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

MAX_AGE = 45.0


def _file_ok() -> bool:
    raw = os.environ.get("SHAHKAR_WORKER_HEARTBEAT")
    if not raw:
        data = os.environ.get("SHAHKAR_DATA_DIR", "/var/lib/shahkar")
        raw = str(Path(data) / "worker.heartbeat")
    p = Path(raw)
    try:
        return p.is_file() and (time.time() - p.stat().st_mtime) < MAX_AGE
    except OSError:
        return False


def _redis_ok() -> bool:
    url = os.environ.get("REDIS_URL") or ""
    if not url:
        return False
    try:
        import redis

        raw = redis.Redis.from_url(
            url, socket_connect_timeout=1, socket_timeout=1
        ).get("shahkar:worker:heartbeat")
        if raw is None:
            return False
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        return (time.time() - float(raw)) < MAX_AGE
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(0 if (_file_ok() or _redis_ok()) else 1)
