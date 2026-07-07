"""Rate limit unauthenticated admin login attempts by IP."""
import ipaddress
import threading
import time
from collections import defaultdict
from typing import DefaultDict, List, Optional, Sequence

from fastapi import HTTPException, Request

_lock = threading.Lock()
_attempts: DefaultDict[str, List[float]] = defaultdict(list)
_redis = None
_redis_checked = False


def _redis_client():
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    try:
        from config import REDIS_URL

        if not REDIS_URL:
            return None
        import redis

        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        _redis.ping()
    except Exception:
        _redis = None
    return _redis


def _ip_in_allowlist(ip: str, allowlist: Sequence[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def enforce_admin_ip_allowlist(client_ip: str, allowlist: Optional[Sequence[str]] = None) -> None:
    """Reject admin auth from IPs outside the configured allow-list.

    An empty/unset allow-list means "allow all" so existing deployments keep
    working. Any malformed client IP is rejected when an allow-list is active.
    """
    if allowlist is None:
        from config import ADMIN_IP_ALLOWLIST as allowlist  # lazy: avoids import cycle
    if not allowlist:
        return
    if not _ip_in_allowlist(client_ip, allowlist):
        raise HTTPException(status_code=403, detail="Admin access is not allowed from this IP")


def enforce_login_rate_limit(
    request: Request,
    *,
    max_attempts: int = 10,
    window_seconds: int = 900,
) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    r = _redis_client()
    if r is not None:
        key = f"nexus:login:{ip}"
        try:
            count = r.incr(key)
            if count == 1:
                r.expire(key, window_seconds)
            if count > max_attempts:
                raise HTTPException(status_code=429, detail="Too many login attempts")
        except HTTPException:
            raise
        except Exception:
            pass
        else:
            return
    with _lock:
        recent = [t for t in _attempts[ip] if now - t < window_seconds]
        if len(recent) >= max_attempts:
            raise HTTPException(status_code=429, detail="Too many login attempts")
        recent.append(now)
        _attempts[ip] = recent
