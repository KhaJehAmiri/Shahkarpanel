"""Rate limit unauthenticated admin login attempts by IP."""
import threading
import time
from collections import defaultdict
from typing import DefaultDict, List

from fastapi import HTTPException, Request

_lock = threading.Lock()
_attempts: DefaultDict[str, List[float]] = defaultdict(list)


def enforce_login_rate_limit(
    request: Request,
    *,
    max_attempts: int = 10,
    window_seconds: int = 900,
) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _lock:
        recent = [t for t in _attempts[ip] if now - t < window_seconds]
        if len(recent) >= max_attempts:
            raise HTTPException(status_code=429, detail="Too many login attempts")
        recent.append(now)
        _attempts[ip] = recent
