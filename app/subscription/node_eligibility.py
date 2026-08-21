"""Which nodes may appear in a generated subscription.

Subscription builders used to take ``status == connected`` at face value. A
node whose control channel blips for a few seconds then disappears from every
profile generated in that window, and clients cache what they fetched (Karing
re-reads the URL about once an hour), so one flap can leave a customer running
on a crippled server list long after the node is healthy again.

So a node keeps its place for a short grace period after it stops reporting
``connected``. Grace is measured from the last time this process actually saw
the node connected, not from ``last_status_change`` -- a node that flaps
connecting/error forever refreshes that column on every bounce and would never
age out. A freshly booted process has seen nothing yet, so it grants grace from
start-up: that is exactly the window where every node still reads ``connecting``
and profiles would otherwise come out empty.

``disabled`` is an operator decision and never gets grace.
"""
from __future__ import annotations

import threading
import time
from typing import Iterable, Optional

from app.models.node import NodeStatus

# Long enough to ride out an RPyC reconnect or an agent restart, short enough
# that a node down for real stops being advertised within one client refresh.
FLAP_GRACE_SEC = 180.0

_LOCK = threading.Lock()
_last_connected: dict[int, float] = {}
_process_start = time.monotonic()


def note_connected(node_id: int, *, seen_at: Optional[float] = None) -> None:
    """Record that ``node_id`` was observed connected."""
    with _LOCK:
        _last_connected[int(node_id)] = seen_at if seen_at is not None else time.monotonic()


def _grace_anchor(node_id: int) -> float:
    with _LOCK:
        return _last_connected.get(int(node_id), _process_start)


def node_is_serviceable(node, *, now: Optional[float] = None) -> bool:
    """True when this node should still be offered to clients."""
    status = getattr(node, "status", None)
    node_id = getattr(node, "id", None)
    if status == NodeStatus.connected:
        if node_id is not None:
            note_connected(node_id, seen_at=now)
        return True
    if status == NodeStatus.disabled or node_id is None:
        return False
    stamp = now if now is not None else time.monotonic()
    return (stamp - _grace_anchor(node_id)) <= FLAP_GRACE_SEC


def serviceable_nodes(nodes: Iterable, *, now: Optional[float] = None) -> list:
    """Filter ``nodes`` down to the ones a subscription may advertise."""
    stamp = now if now is not None else time.monotonic()
    return [n for n in nodes if node_is_serviceable(n, now=stamp)]
