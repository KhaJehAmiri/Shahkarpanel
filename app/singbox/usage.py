"""sing-box traffic collector for unified accounting (Hysteria2 / TUIC).

The node's Clash API reports per-user rx/tx counters; we turn those into
per-interval **deltas** and emit the same ``{"uid", "value"}`` shape every
other collector uses, so sing-box bytes fold into the single
``User.used_traffic`` without over-counting (see ``docs/accounting-contract``).

Pure/isolated tracker so the reset-clamp logic is unit testable without a node.
"""
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from app.db import GetDB, crud
from app.singbox.operations import _node_object, collect_singbox_users
from app.singbox.sync import build_name_user_map
from app.singbox.transport import client_for_node

logger = logging.getLogger("nexus-singbox")


class SingBoxUsageTracker:
    """Turns cumulative per-user readings into per-interval deltas.

    Keyed by ``(node_id, name)``. First observation establishes a baseline
    (delta 0). A counter that goes *down* means sing-box restarted (counters
    reset), so the current value itself is the delta.
    """

    def __init__(self):
        self._last: Dict[Tuple[int, str], int] = {}

    def deltas(self, node_id: int, transfer: Dict[str, dict]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for name, counters in (transfer or {}).items():
            try:
                total = int(counters.get("rx", 0)) + int(counters.get("tx", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            key = (node_id, name)
            last = self._last.get(key)
            self._last[key] = total
            if last is None:
                continue
            delta = total if total < last else total - last
            if delta > 0:
                out[name] = delta
        return out

    def forget_node(self, node_id: int) -> None:
        for key in [k for k in self._last if k[0] == node_id]:
            del self._last[key]


def build_singbox_usage_params(
    deltas_by_node: Dict[int, Dict[str, int]],
    name_user_map: Dict[str, int],
) -> Dict[int, List[dict]]:
    """Map per-node user deltas to ``{node_id: [{"uid", "value"}, ...]}``.

    Unknown user names (no matching user) are dropped — their traffic cannot be
    attributed and must never land on the wrong account.
    """
    result: Dict[int, List[dict]] = {}
    for node_id, user_deltas in deltas_by_node.items():
        agg: Dict[int, int] = defaultdict(int)
        for name, delta in user_deltas.items():
            uid = name_user_map.get(name)
            if uid is None or delta <= 0:
                continue
            agg[uid] += delta
        result[node_id] = [{"uid": uid, "value": value} for uid, value in agg.items()]
    return result


_tracker = SingBoxUsageTracker()


def _interval_bytes(transfer: Dict[str, dict]) -> Dict[str, int]:
    """Sum rx+tx per user from a reset-on-read V2Ray stats poll."""
    out: Dict[str, int] = {}
    for name, counters in (transfer or {}).items():
        try:
            total = int(counters.get("rx", 0)) + int(counters.get("tx", 0))
        except (AttributeError, TypeError, ValueError):
            continue
        if total > 0:
            out[name] = total
    return out


def collect_singbox_usage_params(db=None) -> Tuple[Dict[int, List[dict]], Dict[int, float]]:
    """Read traffic counters from every connected sing-box node and return
    ``(api_params, usage_coefficient)`` deltas in the central accounting shape.

    DB work finishes before node RPCs so hung transfers cannot idle-in-transaction.
    """
    from concurrent.futures import ThreadPoolExecutor

    def _plan(session):
        sb_nodes = crud.get_singbox_nodes(session)
        if not sb_nodes:
            return None
        name_map = build_name_user_map(collect_singbox_users(session))
        plans = [
            {"id": n.id, "coefficient": n.usage_coefficient}
            for n in sb_nodes
            if n.singbox is not None
        ]
        return name_map, plans

    if db is not None:
        planned = _plan(db)
    else:
        with GetDB() as session:
            planned = _plan(session)

    if not planned:
        return {}, {}

    name_map, plans = planned
    deltas_by_node: Dict[int, Dict[str, int]] = {}
    coefficient: Dict[int, float] = {}

    for plan in plans:
        client = client_for_node(_node_object(plan["id"], connect=False))
        if client is None:
            continue
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            transfer = pool.submit(client.transfer).result(timeout=8)
        except Exception as exc:
            logger.warning("sing-box transfer read from node %s failed: %s", plan["id"], exc)
            transfer = None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if not transfer:
            continue
        deltas_by_node[plan["id"]] = _interval_bytes(transfer)
        coefficient[plan["id"]] = plan["coefficient"]

    return build_singbox_usage_params(deltas_by_node, name_map), coefficient


def merge_singbox_usage(
    api_params: Dict[Optional[int], List[dict]],
    usage_coefficient: Dict[Optional[int], float],
    sb_params: Dict[int, List[dict]],
    sb_coefficient: Dict[int, float],
) -> None:
    """Merge sing-box params into the central collector dicts in place."""
    for node_id, params in sb_params.items():
        if not params:
            continue
        api_params.setdefault(node_id, []).extend(params)
        usage_coefficient.setdefault(node_id, sb_coefficient.get(node_id, 1))
