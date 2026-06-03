"""Smart routing: order/select nodes for clients.

Operates on the node metadata captured in phase 2 (``latency_ms``, ``region``,
``capacity``, ``status``). Strategies are pure functions over a list of nodes,
so they are trivially testable and reusable from the subscription layer or the
routing API.

This is application-layer routing (which nodes a client should prefer), not
network-level Anycast/BGP.
"""
import itertools
from typing import List, Optional

from app.models.node import NodeStatus

_INF = float("inf")
_rr_counter = itertools.count()


def _is_usable(node) -> bool:
    status = getattr(node, "status", None)
    value = getattr(status, "value", status)
    return value in (NodeStatus.connected.value, NodeStatus.connecting.value, None)


def _latency(node) -> float:
    latency = getattr(node, "latency_ms", None)
    return latency if latency is not None else _INF


def by_latency(nodes: List) -> List:
    return sorted(nodes, key=_latency)


def by_region(nodes: List, region: Optional[str]) -> List:
    if not region:
        return by_latency(nodes)
    # Same-region nodes first (cheapest), then everything else, each by latency.
    same = [n for n in nodes if (getattr(n, "region", None) == region)]
    other = [n for n in nodes if (getattr(n, "region", None) != region)]
    return by_latency(same) + by_latency(other)


def by_load(nodes: List) -> List:
    # Higher capacity = more headroom = preferred. Unknown capacity sorts last.
    def weight(node):
        capacity = getattr(node, "capacity", None)
        return -(capacity if capacity is not None else -1)

    return sorted(nodes, key=lambda n: (weight(n), _latency(n)))


def round_robin(nodes: List) -> List:
    if not nodes:
        return []
    ordered = by_latency(nodes)
    offset = next(_rr_counter) % len(ordered)
    return ordered[offset:] + ordered[:offset]


STRATEGIES = {
    "latency": lambda nodes, region: by_latency(nodes),
    "region": lambda nodes, region: by_region(nodes, region),
    "load": lambda nodes, region: by_load(nodes),
    "round_robin": lambda nodes, region: round_robin(nodes),
}


def select_nodes(
    nodes: List,
    strategy: str = "latency",
    region: Optional[str] = None,
    limit: Optional[int] = None,
    usable_only: bool = True,
) -> List:
    """Return ``nodes`` ordered by ``strategy`` (best first)."""
    candidates = [n for n in nodes if _is_usable(n)] if usable_only else list(nodes)
    fn = STRATEGIES.get(strategy, STRATEGIES["latency"])
    ordered = fn(candidates, region)
    return ordered[:limit] if limit else ordered


def available_strategies() -> List[str]:
    return sorted(STRATEGIES)
