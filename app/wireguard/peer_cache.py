"""In-process WireGuard peer cache for high-scale usage/sync paths.

``collect_wg_peers`` used to N+1 lazy-load every ``proxy.user`` on each 5s
usage tick. At tens/hundreds of thousands of peers that overruns the job
interval (``max_instances=1`` skips) and pegs the panel CPU.

This cache:
- loads peers with a single ``joinedload(Proxy.user)`` query
- serves pubkey→uid maps for usage without hitting Postgres every cycle
- invalidates on membership/settings changes (``sync_user_change``, etc.)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

from app.wireguard.sync import WGUserPeer, build_pubkey_user_map

logger = logging.getLogger("shahkar-wg")

# Soft TTL: even without an explicit invalidate, refresh occasionally so a
# missed invalidate cannot drift forever. Hard rebuilds still go through
# ``invalidate()`` on user/proxy changes.
_DEFAULT_TTL_SEC = 60.0


class WireGuardPeerCache:
    def __init__(self, ttl_sec: float = _DEFAULT_TTL_SEC):
        self._lock = threading.RLock()
        self._ttl_sec = float(ttl_sec)
        self._generation = 0
        self._peers: Optional[List[WGUserPeer]] = None
        self._pubkey_map: Optional[Dict[str, int]] = None
        self._loaded_at = 0.0
        self._loaded_generation = -1

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def invalidate(self) -> int:
        """Bump generation and drop cached peers. Returns new generation."""
        with self._lock:
            self._generation += 1
            self._peers = None
            self._pubkey_map = None
            self._loaded_at = 0.0
            self._loaded_generation = -1
            gen = self._generation
        logger.debug("WireGuard peer cache invalidated (generation=%s)", gen)
        return gen

    def _stale_unlocked(self) -> bool:
        if self._peers is None or self._pubkey_map is None:
            return True
        if self._loaded_generation != self._generation:
            return True
        if (time.monotonic() - self._loaded_at) > self._ttl_sec:
            return True
        return False

    def _reload_unlocked(self, db) -> None:
        from app.wireguard.operations import collect_wg_peers_uncached

        peers = collect_wg_peers_uncached(db)
        self._peers = peers
        self._pubkey_map = build_pubkey_user_map(peers)
        self._loaded_at = time.monotonic()
        self._loaded_generation = self._generation
        logger.debug(
            "WireGuard peer cache reloaded peers=%s generation=%s",
            len(peers),
            self._generation,
        )

    def get_peers(self, db=None) -> List[WGUserPeer]:
        """Return cached peers, loading from ``db`` (or a fresh session) if stale."""
        with self._lock:
            if not self._stale_unlocked():
                return list(self._peers or [])
            if db is not None:
                self._reload_unlocked(db)
                return list(self._peers or [])

        from app.db import GetDB

        with GetDB() as session:
            with self._lock:
                if not self._stale_unlocked():
                    return list(self._peers or [])
                self._reload_unlocked(session)
                return list(self._peers or [])

    def get_pubkey_map(self, db=None) -> Dict[str, int]:
        with self._lock:
            if not self._stale_unlocked():
                return dict(self._pubkey_map or {})
            if db is not None:
                self._reload_unlocked(db)
                return dict(self._pubkey_map or {})

        from app.db import GetDB

        with GetDB() as session:
            with self._lock:
                if not self._stale_unlocked():
                    return dict(self._pubkey_map or {})
                self._reload_unlocked(session)
                return dict(self._pubkey_map or {})

    def snapshot(self, db=None) -> Tuple[List[WGUserPeer], Dict[str, int], int]:
        peers = self.get_peers(db)
        with self._lock:
            return peers, dict(self._pubkey_map or {}), self._generation


peer_cache = WireGuardPeerCache()
