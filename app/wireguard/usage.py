"""WireGuard traffic collector for unified accounting (Phase 11.4).

``wg show <iface> transfer`` reports **cumulative** rx/tx counters per peer
(since the peer was added), unlike Xray's ``get_users_stats(reset=True)`` which
zeroes on read. To fold WireGuard bytes into the single ``User.used_traffic``
without over-counting we must turn those cumulative counters into per-interval
**deltas** and emit the exact same ``{"uid", "value"}`` shape every other
collector uses — see ``docs/accounting-contract.md``.

The delta tracker and the param builder are pure/stateful-but-isolated so the
reset-clamp logic is unit testable without a live node.
"""
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from app.db import GetDB, crud
from app.wireguard.operations import _node_object, collect_wg_peers
from app.wireguard.sync import build_pubkey_user_map
from app.wireguard.transport import client_for_node

logger = logging.getLogger("nexus-wg")


class WireGuardUsageTracker:
    """Turns cumulative ``transfer`` readings into per-interval deltas.

    Keyed by ``(node_id, public_key)``. The first observation of a key only
    establishes a baseline (delta 0). A counter that goes *down* means the
    interface or peer was recreated (counters reset to 0), so the current value
    itself is the delta.
    """

    def __init__(self):
        self._last: Dict[Tuple[int, str], int] = {}

    def deltas(self, node_id: int, transfer: Dict[str, dict]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for public_key, counters in (transfer or {}).items():
            try:
                total = int(counters.get("rx", 0)) + int(counters.get("tx", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            key = (node_id, public_key)
            last = self._last.get(key)
            self._last[key] = total
            if last is None:
                continue  # baseline only
            delta = total if total < last else total - last
            if delta > 0:
                out[public_key] = delta
        return out

    def forget_node(self, node_id: int) -> None:
        for key in [k for k in self._last if k[0] == node_id]:
            del self._last[key]


def build_wg_usage_params(
    deltas_by_node: Dict[int, Dict[str, int]],
    pubkey_user_map: Dict[str, int],
) -> Dict[int, List[dict]]:
    """Map per-node peer deltas to ``{node_id: [{"uid", "value"}, ...]}``.

    Unknown public keys (no matching user) are dropped — their traffic cannot
    be attributed and must never land on the wrong account.
    """
    result: Dict[int, List[dict]] = {}
    for node_id, peer_deltas in deltas_by_node.items():
        agg: Dict[int, int] = defaultdict(int)
        for public_key, delta in peer_deltas.items():
            uid = pubkey_user_map.get(public_key)
            if uid is None or delta <= 0:
                continue
            agg[uid] += delta
        result[node_id] = [{"uid": uid, "value": value} for uid, value in agg.items()]
    return result


# Single leader-scoped tracker (record_user_usages runs under run_if_leader).
_tracker = WireGuardUsageTracker()


def collect_wg_usage_params(db=None) -> Tuple[Dict[int, List[dict]], Dict[int, float]]:
    """Read transfer counters from every connected WireGuard node and return
    ``(api_params, usage_coefficient)`` deltas in the central accounting shape.

    Best-effort per node: a node that is disconnected or errors is simply
    skipped this cycle.
    """
    def _run(session) -> Tuple[Dict[int, List[dict]], Dict[int, float]]:
        wg_nodes = crud.get_wireguard_nodes(session)
        if not wg_nodes:
            return {}, {}

        pubkey_map = build_pubkey_user_map(collect_wg_peers(session))
        deltas_by_node: Dict[int, Dict[str, int]] = {}
        coefficient: Dict[int, float] = {}

        for dbnode in wg_nodes:
            cfg = dbnode.wireguard
            client = client_for_node(_node_object(dbnode.id))
            if cfg is None or client is None:
                continue
            from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

            combined: Dict[str, dict] = {}
            interfaces = []
            if plain_wg_enabled(cfg):
                interfaces.append(cfg.interface)
            if amneziawg_enabled(cfg):
                interfaces.append(cfg.awg_interface)
            for iface in interfaces:
                try:
                    part = client.transfer(iface)
                except Exception as exc:
                    logger.warning(
                        "WireGuard transfer read from node %s iface %s failed: %s",
                        dbnode.id, iface, exc,
                    )
                    continue
                for pubkey, counters in (part or {}).items():
                    prev = combined.get(pubkey, {"rx": 0, "tx": 0})
                    combined[pubkey] = {
                        "rx": int(prev.get("rx", 0)) + int(counters.get("rx", 0)),
                        "tx": int(prev.get("tx", 0)) + int(counters.get("tx", 0)),
                    }
            if not combined:
                continue
            deltas_by_node[dbnode.id] = _tracker.deltas(dbnode.id, combined)
            coefficient[dbnode.id] = dbnode.usage_coefficient

        return build_wg_usage_params(deltas_by_node, pubkey_map), coefficient

    if db is not None:
        return _run(db)
    with GetDB() as session:
        return _run(session)


def merge_wg_usage(
    api_params: Dict[Optional[int], List[dict]],
    usage_coefficient: Dict[Optional[int], float],
    wg_params: Dict[int, List[dict]],
    wg_coefficient: Dict[int, float],
) -> None:
    """Merge WireGuard params into the central collector dicts in place.

    WG node ids are distinct from the local core (``None``); a WG node carries
    no Xray per-user stats, so extending its (empty) entry never double-counts.
    """
    for node_id, params in wg_params.items():
        if not params:
            continue
        api_params.setdefault(node_id, []).extend(params)
        usage_coefficient.setdefault(node_id, wg_coefficient.get(node_id, 1))
