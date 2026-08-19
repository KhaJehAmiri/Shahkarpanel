"""Rate limiter for unauthenticated node bootstrap (Redis when available)."""
import threading
import time
from collections import defaultdict
from typing import DefaultDict, List

from fastapi import HTTPException, Request

_lock = threading.Lock()
_attempts: DefaultDict[str, List[float]] = defaultdict(list)


def _redis():
    try:
        from config import REDIS_URL

        if not REDIS_URL:
            return None
        import redis

        return redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.5,
        )
    except Exception:
        return None


def enforce_bootstrap_rate_limit(
    request: Request,
    *,
    max_attempts: int = 20,
    window_seconds: int = 3600,
) -> None:
    """Raise 429 when an IP exceeds bootstrap attempts in the sliding window."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    client = _redis()
    if client is not None:
        key = f"shahkar:bootstrap:{ip}"
        try:
            count = int(client.incr(key) or 0)
            if count == 1:
                client.expire(key, window_seconds)
            if count > max_attempts:
                raise HTTPException(status_code=429, detail="Too many bootstrap attempts")
            return
        except HTTPException:
            raise
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass
    with _lock:
        recent = [t for t in _attempts[ip] if now - t < window_seconds]
        if len(recent) >= max_attempts:
            raise HTTPException(status_code=429, detail="Too many bootstrap attempts")
        recent.append(now)
        _attempts[ip] = recent
