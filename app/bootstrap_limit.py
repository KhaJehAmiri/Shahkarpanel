"""In-memory rate limiter for unauthenticated node bootstrap."""
import threading
import time
from collections import defaultdict
from typing import DefaultDict, List

from fastapi import HTTPException, Request

_lock = threading.Lock()
_attempts: DefaultDict[str, List[float]] = defaultdict(list)


def enforce_bootstrap_rate_limit(
    request: Request,
    *,
    max_attempts: int = 20,
    window_seconds: int = 3600,
) -> None:
    """Raise 429 when an IP exceeds bootstrap attempts in the sliding window."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _lock:
        recent = [t for t in _attempts[ip] if now - t < window_seconds]
        if len(recent) >= max_attempts:
            raise HTTPException(status_code=429, detail="Too many bootstrap attempts")
        recent.append(now)
        _attempts[ip] = recent
