"""Deferred cumulative→delta baselines for usage billing.

Collectors that read *cumulative* counters (WireGuard, Finalmask, sing-box,
Xray with reset=False) must not advance their baseline until the matching DB
bill succeeds. Baselines are persisted in Redis so a worker restart cannot
re-bill lifetime counters as a single interval.
"""
from __future__ import annotations

import logging
from typing import Dict, Hashable, Optional, Tuple

logger = logging.getLogger("shahkar-usage-baselines")

_BASELINE_TTL_SEC = 7 * 24 * 3600


def _redis_store():
    try:
        from config import REDIS_URL

        if not REDIS_URL:
            return None
        import redis

        return redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=1.0, socket_timeout=1.5
        )
    except Exception:
        return None


def _max_delta_bytes() -> int:
    try:
        from config import USAGE_MAX_DELTA_BYTES

        return max(0, int(USAGE_MAX_DELTA_BYTES or 0))
    except Exception:
        return 524_288_000  # 500 MiB per user per tick


class CumulativeByteTracker:
    """Keyed cumulative totals → per-interval deltas with peek/commit."""

    def __init__(self, *, redis_prefix: str = "shahkar:usage:bl", store=None):
        self._last: Dict[Tuple[Hashable, str], int] = {}
        self._redis_prefix = redis_prefix
        self._store = _redis_store() if store is None else store

    def _redis_key(self, group_id: Hashable, name: str) -> str:
        return f"{self._redis_prefix}:{group_id}:{name}"

    def _load_last(self, key: Tuple[Hashable, str]) -> Optional[int]:
        cached = self._last.get(key)
        if cached is not None:
            return cached
        if not self._store:
            return None
        try:
            raw = self._store.get(self._redis_key(key[0], key[1]))
        except Exception:
            return None
        if raw is None:
            return None
        try:
            val = int(raw)
        except (TypeError, ValueError):
            return None
        self._last[key] = val
        return val

    def _save_last(self, key: Tuple[Hashable, str], total: int) -> None:
        self._last[key] = total
        if not self._store:
            return
        try:
            self._store.set(
                self._redis_key(key[0], key[1]),
                int(total),
                ex=_BASELINE_TTL_SEC,
            )
        except Exception:
            logger.debug("baseline persist failed for %s", key, exc_info=True)

    def peek_deltas(
        self,
        group_id: Hashable,
        transfer: Dict[str, dict],
        *,
        rx_key: str = "rx",
        tx_key: str = "tx",
    ) -> Tuple[Dict[str, int], dict]:
        out: Dict[str, int] = {}
        new_last: Dict[Tuple[Hashable, str], int] = {}
        cap = _max_delta_bytes()
        for name, counters in (transfer or {}).items():
            try:
                total = int(counters.get(rx_key, 0)) + int(counters.get(tx_key, 0))
            except (AttributeError, TypeError, ValueError):
                continue
            key = (group_id, str(name))
            last = self._load_last(key)
            # Always advance pending baseline to the observed cumulative so a
            # successful bill (or resync) never re-reads the same jump.
            new_last[key] = total
            if last is None:
                continue
            if total < last:
                # Core/counter reset: current reading is the interval delta.
                delta = total
            else:
                delta = total - last
            if delta <= 0:
                continue
            if cap and delta > cap:
                # Implausible jump (lost/desynced baseline, not real 5s traffic).
                # Resync baseline immediately and bill nothing — charging ``cap``
                # every tick used to drain accounts at ~6 MB/s until caught up.
                logger.warning(
                    "usage delta discarded (resync) group=%s name=%s delta=%s cap=%s total=%s last=%s",
                    group_id,
                    name,
                    delta,
                    cap,
                    total,
                    last,
                )
                self._save_last(key, total)
                continue
            out[str(name)] = delta
        pending = {"new_last": new_last}
        return out, pending

    def peek_from_totals(
        self, group_id: Hashable, totals: Dict[str, int]
    ) -> Tuple[Dict[str, int], dict]:
        """Same as peek_deltas but when the input is already ``name → total``."""
        fake = {name: {"rx": int(total), "tx": 0} for name, total in (totals or {}).items()}
        return self.peek_deltas(group_id, fake)

    def commit_pending(self, pending: Optional[dict]) -> None:
        if not pending:
            return
        for key, total in (pending.get("new_last") or {}).items():
            self._save_last(key, total)

    def forget_group(self, group_id: Hashable) -> None:
        keys = [k for k in self._last if k[0] == group_id]
        for key in keys:
            del self._last[key]
            if not self._store:
                continue
            try:
                self._store.delete(self._redis_key(key[0], key[1]))
            except Exception:
                pass


def commit_pending_list(tracker: CumulativeByteTracker, pending_list: list) -> None:
    for item in pending_list or []:
        tracker.commit_pending(item)
