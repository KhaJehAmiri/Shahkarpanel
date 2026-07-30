"""High-availability leader election.

When several panel instances share one database, background jobs that must run
exactly once (usage recording, notifications, backups, failover detection) have
to be coordinated. This module provides a Redis-backed leader lock:

* The leader holds a key (``shahkar:leader``) with a short TTL and renews it.
* Non-leaders periodically try to acquire the (expired) key.
* :func:`is_leader` tells callers whether *this* instance currently leads.

Without Redis (single instance) the instance is always the leader, so the
behaviour is identical to today's single-process deployment.
"""
import logging
import os
import socket
import threading
from typing import Optional

from config import HA_ENABLED, HA_INSTANCE_ID, HA_LEADER_TTL, REDIS_URL

logger = logging.getLogger("uvicorn.error")

_LEADER_KEY = "shahkar:leader"

_instance_id = HA_INSTANCE_ID or f"{socket.gethostname()}:{os.getpid()}"
_redis = None
_is_leader = True  # default for single-instance / HA disabled
_lock = threading.Lock()
_renewer: Optional[threading.Thread] = None
_stop = threading.Event()


def instance_id() -> str:
    return _instance_id


def _connect():
    global _redis
    if _redis is not None:
        return _redis
    import redis  # imported lazily so the dependency is optional

    _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _try_acquire_or_renew() -> bool:
    """Acquire leadership if free, or renew it if we already hold it."""
    client = _connect()
    ttl_ms = max(HA_LEADER_TTL, 2) * 1000

    # Atomic: take the key if absent.
    if client.set(_LEADER_KEY, _instance_id, nx=True, px=ttl_ms):
        return True

    # Already owned — renew only if it's ours.
    if client.get(_LEADER_KEY) == _instance_id:
        client.set(_LEADER_KEY, _instance_id, px=ttl_ms)
        return True

    return False


def _renew_loop() -> None:
    interval = max(HA_LEADER_TTL // 3, 1)
    while not _stop.wait(interval):
        global _is_leader
        try:
            leader = _try_acquire_or_renew()
        except Exception:
            logger.exception("HA leader renew failed; assuming follower")
            leader = False
        with _lock:
            if leader != _is_leader:
                logger.info(
                    "HA role change: this instance (%s) is now %s",
                    _instance_id, "LEADER" if leader else "follower",
                )
            _is_leader = leader


def start() -> None:
    """Begin participating in leader election (no-op when HA is disabled)."""
    global _renewer, _is_leader
    if not (HA_ENABLED and REDIS_URL):
        _is_leader = True
        logger.info("HA disabled; this instance is the sole leader")
        return
    if _renewer is not None:
        return
    try:
        _is_leader = _try_acquire_or_renew()
    except Exception:
        logger.exception("HA initial acquire failed; starting as follower")
        _is_leader = False
    _renewer = threading.Thread(target=_renew_loop, name="ha-leader", daemon=True)
    _renewer.start()
    logger.info("HA enabled (instance=%s, ttl=%ds)", _instance_id, HA_LEADER_TTL)


def stop() -> None:
    _stop.set()
    if _redis is not None:
        try:
            # Release the lock if we own it so failover is immediate.
            if _redis.get(_LEADER_KEY) == _instance_id:
                _redis.delete(_LEADER_KEY)
        except Exception:
            pass


def is_leader() -> bool:
    with _lock:
        return _is_leader


def run_if_leader(func):
    """Wrap a scheduler job so it only runs on the leader instance."""
    def wrapper(*args, **kwargs):
        if not is_leader():
            return None
        return func(*args, **kwargs)

    wrapper.__name__ = getattr(func, "__name__", "wrapped")
    return wrapper
