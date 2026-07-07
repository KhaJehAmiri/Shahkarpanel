"""Pick the best node for subscription / client materials."""
from __future__ import annotations

from typing import List, Optional, TypeVar

T = TypeVar("T")


def pick_node(nodes: List[T], node_id: Optional[int] = None) -> Optional[T]:
    """Choose a node: explicit id, else lowest-latency, else first."""
    if not nodes:
        return None
    if node_id is not None:
        match = next((n for n in nodes if getattr(n, "id", None) == node_id), None)
        if match:
            return match
    ranked = sorted(
        nodes,
        key=lambda n: (
            getattr(n, "latency_ms", None) is None,
            getattr(n, "latency_ms", None) or 99999.0,
            getattr(n, "id", 0),
        ),
    )
    return ranked[0]
