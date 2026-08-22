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
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from app.db import GetDB, crud
from app.wireguard.operations import _node_object
from app.wireguard.peer_cache import peer_cache
from app.wireguard.transport import client_for_node

logger = logging.getLogger("shahkar-wg")


class WireGuardUsageTracker:
    """Turns cumulative ``transfer`` readings into per-interval deltas.

    Keyed by ``(node_id, public_key)``. The first observation of a key only
    establishes a baseline (delta 0). A counter that goes *down* means the
    interface or peer was recreated (counters reset to 0), so the current value
    itself is the delta.

    Baselines advance only via ``commit_pending`` after a successful DB bill.
    """

    def __init__(self):
        from app.usage_baselines import CumulativeByteTracker

        self._inner = CumulativeByteTracker(redis_prefix="shahkar:usage:wg")

    def deltas(self, node_id, transfer: Dict[str, dict]) -> Dict[str, int]:
        out, pending = self.peek_deltas(node_id, transfer)
        self.commit_pending(pending)
        return out

    def peek_deltas(self, node_id, transfer: Dict[str, dict]):
        return self._inner.peek_deltas(node_id, transfer)

    def commit_pending(self, pending) -> None:
        self._inner.commit_pending(pending)

    def forget_node(self, node_id) -> None:
        self._inner.forget_group(node_id)


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
# Separate tracker for the panel host's own WG exit interface(s). Keyed by the
# same ``(node_id, pubkey)`` scheme with a ``None`` node id (the panel host).
_panel_host_tracker = WireGuardUsageTracker()


def collect_wg_usage_params(
    db=None,
) -> Tuple[Dict[int, List[dict]], Dict[int, float], list]:
    """Read transfer counters from every connected WireGuard node.

    Returns ``(api_params, usage_coefficient, pending_baselines)``.
    """
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled
    from app.wireguard.wg_manager import autoscale_enabled, collect_autoscale_transfer

    def _plan(session):
        wg_nodes = crud.get_wireguard_nodes(session)
        if not wg_nodes:
            return None
        pubkey_map = peer_cache.get_pubkey_map(session)
        plans = []
        for dbnode in wg_nodes:
            cfg = dbnode.wireguard
            if cfg is None:
                continue
            interfaces = []
            need_autoscale = False
            if plain_wg_enabled(cfg):
                if autoscale_enabled():
                    need_autoscale = True
                else:
                    interfaces.append(cfg.interface)
            if amneziawg_enabled(cfg):
                interfaces.append(cfg.awg_interface)
            plans.append({
                "id": dbnode.id,
                "coefficient": dbnode.usage_coefficient,
                "interfaces": interfaces,
                "need_autoscale": need_autoscale,
            })
        return pubkey_map, plans

    if db is not None:
        planned = _plan(db)
    else:
        with GetDB() as session:
            planned = _plan(session)

    if not planned:
        return {}, {}, []

    pubkey_map, plans = planned
    deltas_by_node: Dict[int, Dict[str, int]] = {}
    coefficient: Dict[int, float] = {}
    pending: list = []

    def _one(_nid, plan: dict):
        client = client_for_node(_node_object(plan["id"], connect=False))
        if client is None and not plan["need_autoscale"]:
            return None
        combined: Dict[str, dict] = {}
        if plan["need_autoscale"]:
            try:
                with GetDB() as session:
                    combined = collect_autoscale_transfer(session, plan["id"])
            except Exception as exc:
                logger.warning(
                    "WireGuard autoscale transfer from node %s failed: %s",
                    plan["id"], exc,
                )
                combined = {}
        for iface in plan["interfaces"]:
            if client is None:
                break
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                # Cap well under the 5s usage interval; map_rpc applies one
                # wall-clock budget across the fleet (not N × timeout).
                part = pool.submit(client.transfer, iface).result(timeout=1)
            except Exception as exc:
                logger.warning(
                    "WireGuard transfer read from node %s iface %s failed: %s",
                    plan["id"], iface, exc,
                )
                part = None
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            if not part:
                continue
            for pubkey, counters in part.items():
                prev = combined.get(pubkey, {"rx": 0, "tx": 0})
                combined[pubkey] = {
                    "rx": int(prev.get("rx", 0)) + int(counters.get("rx", 0)),
                    "tx": int(prev.get("tx", 0)) + int(counters.get("tx", 0)),
                }
        if not combined:
            return None
        peer_deltas, pend = _tracker.peek_deltas(plan["id"], combined)
        return plan["id"], peer_deltas, plan["coefficient"], pend

    from app.utils.concurrency import map_rpc

    indexed = {int(plan["id"]): plan for plan in plans}
    results = map_rpc(_one, indexed, timeout=1.5, default=None)
    for node_id, result in results.items():
        if not result:
            continue
        try:
            nid, email_deltas, coef, pend = result
        except Exception:
            continue
        coefficient[nid] = coef
        if pend:
            pending.append(pend)
        if email_deltas:
            deltas_by_node[nid] = email_deltas

    return build_wg_usage_params(deltas_by_node, pubkey_map), coefficient, pending


def commit_wg_pending(pending: list) -> None:
    for item in pending or []:
        _tracker.commit_pending(item)


def collect_panel_host_wg_usage_params(
    db=None,
) -> Tuple[Dict[Optional[int], List[dict]], Dict[Optional[int], float], list]:
    """Collect per-peer WireGuard usage from the PANEL HOST's own interface(s).

    When a tunnel's exit is the panel itself (``exit_node_id is NULL`` and the
    relay delegates native WireGuard to the panel host), user traffic exits via
    the panel host's kernel ``wg0`` — not any remote node. ``collect_wg_usage_params``
    only reads remote WireGuard nodes, so without this collector that traffic is
    never billed and ``online_at`` never advances (Overview / online-user freeze).

    Returns ``({None: [{"uid", "value"}, ...]}, {None: 1}, pending)`` so it merges
    into the local core's slot via :func:`merge_wg_usage`.
    """
    from app.tunnel.relay import canonical_panel_exit_wireguard, panel_tunnel_exit_active
    from app.wireguard.host_sync import read_host_wireguard_transfer
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

    def _plan(session):
        if not panel_tunnel_exit_active(session):
            return None
        cfg = canonical_panel_exit_wireguard(session)
        if cfg is None:
            return None
        interfaces: List[str] = []
        if plain_wg_enabled(cfg) and cfg.interface:
            interfaces.append(cfg.interface)
        if amneziawg_enabled(cfg) and cfg.awg_interface:
            interfaces.append(cfg.awg_interface)
        if not interfaces:
            return None
        pubkey_map = peer_cache.get_pubkey_map(session)
        return pubkey_map, interfaces

    if db is not None:
        planned = _plan(db)
    else:
        with GetDB() as session:
            planned = _plan(session)

    if not planned:
        return {}, {}, []

    pubkey_map, interfaces = planned
    combined: Dict[str, dict] = {}
    for iface in interfaces:
        part = read_host_wireguard_transfer(iface)
        for pubkey, counters in (part or {}).items():
            prev = combined.get(pubkey, {"rx": 0, "tx": 0})
            combined[pubkey] = {
                "rx": int(prev.get("rx", 0)) + int(counters.get("rx", 0)),
                "tx": int(prev.get("tx", 0)) + int(counters.get("tx", 0)),
            }

    if not combined:
        return {}, {}, []

    deltas, pend = _panel_host_tracker.peek_deltas(None, combined)
    pending = [pend] if pend else []
    return build_wg_usage_params({None: deltas}, pubkey_map), {None: 1}, pending


def commit_panel_host_wg_pending(pending: list) -> None:
    for item in pending or []:
        _panel_host_tracker.commit_pending(item)


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
