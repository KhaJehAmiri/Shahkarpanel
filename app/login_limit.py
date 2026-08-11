"""Rate limit unauthenticated login attempts by real client IP."""
from __future__ import annotations

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


def get_request_client_ip(request: Request) -> str:
    """Client IP for rate limits — must use proxy headers behind nginx.

    Using bare ``request.client.host`` keys every browser behind the reverse
    proxy to the same docker/bridge address, so one shared bucket of 10 tries
    locks out the whole panel (``429 Too many login attempts``).
    """
    forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real = (request.headers.get("X-Real-IP") or request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _redis_key(ip: str) -> str:
    return f"shahkar:login:{ip}"


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
    """Raise 429 when this client IP already burned its failed-login budget.

    Does **not** increment — call :func:`record_login_failure` after a bad
    password so successful logins never lock the office/CGNAT IP.
    """
    ip = get_request_client_ip(request)
    now = time.time()
    r = _redis_client()
    if r is not None:
        key = _redis_key(ip)
        try:
            raw = r.get(key)
            count = int(raw or 0)
            if count >= max_attempts:
                raise HTTPException(status_code=429, detail="Too many login attempts")
        except HTTPException:
            raise
        except Exception:
            pass
        else:
            return
    with _lock:
        recent = [t for t in _attempts[ip] if now - t < window_seconds]
        _attempts[ip] = recent
        if len(recent) >= max_attempts:
            raise HTTPException(status_code=429, detail="Too many login attempts")


def record_login_failure(
    request: Request,
    *,
    window_seconds: int = 900,
) -> None:
    """Count one failed login toward the IP budget."""
    ip = get_request_client_ip(request)
    now = time.time()
    r = _redis_client()
    if r is not None:
        key = _redis_key(ip)
        try:
            count = r.incr(key)
            if count == 1:
                r.expire(key, window_seconds)
        except Exception:
            pass
        else:
            return
    with _lock:
        recent = [t for t in _attempts[ip] if now - t < window_seconds]
        recent.append(now)
        _attempts[ip] = recent


def clear_login_failures(request: Request) -> None:
    """Reset the failed-login counter after a successful authentication."""
    ip = get_request_client_ip(request)
    r = _redis_client()
    if r is not None:
        try:
            r.delete(_redis_key(ip))
        except Exception:
            pass
    with _lock:
        _attempts.pop(ip, None)
