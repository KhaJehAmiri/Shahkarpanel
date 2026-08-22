"""Deferred cumulative→delta baselines for usage billing.

Collectors that read *cumulative* counters (WireGuard, Finalmask, sing-box,
Xray with reset=False) must not advance their baseline until the matching DB
bill succeeds. Otherwise a statement_timeout / deadlock after collect
permanently drops those bytes on the next tick.
"""
from __future__ import annotations

from typing import Dict, Hashable, Optional, Tuple


class CumulativeByteTracker:
    """Keyed cumulative totals → per-interval deltas with peek/commit."""

    def __init__(self):
        self._last: Dict[Tuple[Hashable, str], int] = {}

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
        for name, counters in (transfer or {}).items():
            try:
                total = int(counters.get(rx_key, 0)) + int(counters.get(tx_key, 0))
            except (AttributeError, TypeError, ValueError):
                continue
            key = (group_id, str(name))
            last = self._last.get(key)
            new_last[key] = total
            if last is None:
                continue
            delta = total if total < last else total - last
            if delta > 0:
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
            self._last[key] = total

    def forget_group(self, group_id: Hashable) -> None:
        for key in [k for k in self._last if k[0] == group_id]:
            del self._last[key]


def commit_pending_list(tracker: CumulativeByteTracker, pending_list: list) -> None:
    for item in pending_list or []:
        tracker.commit_pending(item)
