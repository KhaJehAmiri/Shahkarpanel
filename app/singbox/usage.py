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

logger = logging.getLogger("shahkar-singbox")

# Long enough to survive a panel deploy, short enough that a node retired for
# days does not pin a stale incarnation id.
_EPOCH_TTL_SEC = 7 * 24 * 3600


def _redis_store():
    """Shared Redis handle, or ``None`` — the tracker degrades to memory."""
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


class SingBoxUsageTracker:
    """Turns cumulative per-user readings into per-interval deltas.

    Keyed by ``(node_id, name)``. A counter that goes *down* means sing-box
    restarted (counters reset), so the current value itself is the delta.

    The first reading of an engine incarnation (``epoch``) counts in full:
    sing-box counters start at zero when the process does, and treating that
    reading as a mere baseline threw away everything a client had transferred
    since the restart — with the engine recycling on every config push, AnyTLS
    / Hysteria2 / TUIC users could stay connected and never be billed. Only a
    reading whose epoch we have *never* seen but that carries a remembered
    baseline (panel restart, engine untouched) is diffed against that baseline.
    """

    def __init__(self, store=None):
        self._last: Dict[Tuple[int, str], int] = {}
        self._epochs: Dict[int, str] = {}
        # ``store=False`` keeps the tracker purely in memory (tests).
        self._store = _redis_store() if store is None else store

    def _load_epoch(self, node_id: int) -> Optional[str]:
        if node_id in self._epochs:
            return self._epochs[node_id]
        if self._store:
            try:
                stored = self._store.get(f"shahkar:sb:epoch:{node_id}")
            except Exception:
                stored = None
            if stored is not None:
                epoch = stored.decode() if isinstance(stored, bytes) else str(stored)
                self._epochs[node_id] = epoch
                return epoch
        return None

    def _save_epoch(self, node_id: int, epoch: str) -> None:
        self._epochs[node_id] = epoch
        if not self._store:
            return
        try:
            self._store.set(f"shahkar:sb:epoch:{node_id}", epoch, ex=_EPOCH_TTL_SEC)
        except Exception:
            logger.debug("sing-box epoch persist failed for node %s", node_id, exc_info=True)

    def deltas(
        self, node_id: int, transfer: Dict[str, dict], epoch: str = ""
    ) -> Dict[str, int]:
        """Compute deltas and advance baselines (legacy one-shot path)."""
        out, pending = self.peek_deltas(node_id, transfer, epoch)
        self.commit_pending(pending)
        return out

    def peek_deltas(
        self, node_id: int, transfer: Dict[str, dict], epoch: str = ""
    ) -> Tuple[Dict[str, int], dict]:
        """Compute deltas without advancing baselines until ``commit_pending``.

        If billing fails after collect, the next tick must see the same bytes
        again — otherwise AnyTLS/Hy2/TUIC traffic is permanently lost.
        """
        known_epoch = self._load_epoch(node_id)
        fresh_engine = bool(epoch) and epoch != known_epoch
        out: Dict[str, int] = {}
        new_last: Dict[Tuple[int, str], int] = {}
        for name, counters in (transfer or {}).items():
            try:
                total = int(counters.get("rx", 0)) + int(counters.get("tx", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            key = (node_id, name)
            last = self._last.get(key)
            new_last[key] = total
            if last is None:
                if not fresh_engine:
                    continue
                delta = total
            else:
                delta = total if total < last else total - last
            if delta > 0:
                out[name] = delta
        pending = {
            "node_id": node_id,
            "epoch": epoch if epoch else None,
            "fresh_engine": fresh_engine,
            "new_last": new_last,
            "transfer_names": set((transfer or {}) or []),
        }
        return out, pending

    def commit_pending(self, pending: Optional[dict]) -> None:
        if not pending:
            return
        node_id = int(pending["node_id"])
        epoch = pending.get("epoch")
        if epoch:
            self._save_epoch(node_id, str(epoch))
        for key, total in (pending.get("new_last") or {}).items():
            self._last[key] = total
        if pending.get("fresh_engine"):
            names = pending.get("transfer_names") or set()
            for key in [k for k in self._last if k[0] == node_id and k[1] not in names]:
                del self._last[key]

    def forget_node(self, node_id: int) -> None:
        for key in [k for k in self._last if k[0] == node_id]:
            del self._last[key]
        self._epochs.pop(node_id, None)


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


def split_transfer(transfer: Dict[str, dict]) -> Tuple[str, str, Dict[str, dict]]:
    """Split a node reading into ``(source, engine epoch, per-user counters)``.

    ``clash`` marks cumulative counters (Clash / V2Ray read without reset);
    anything else is already interval bytes.
    """
    raw = dict(transfer or {})
    source = str(raw.pop("__source__", "") or "")
    epoch = str(raw.pop("__epoch__", "") or "")
    if source in ("clash", "cumulative"):
        return "clash", epoch, raw
    return "v2ray", epoch, raw


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


def deltas_from_transfer(
    node_id: int,
    transfer: Dict[str, dict],
    tracker: SingBoxUsageTracker,
) -> Tuple[Dict[str, int], Optional[dict]]:
    source, epoch, users = split_transfer(transfer)
    if source == "clash":
        return tracker.peek_deltas(node_id, users, epoch)
    return _interval_bytes(users), None


def collect_singbox_usage_params(
    db=None,
) -> Tuple[Dict[int, List[dict]], Dict[int, float], list]:
    """Read traffic counters from every connected sing-box node.

    Returns ``(api_params, usage_coefficient, pending_baselines)``. Call
    ``commit_singbox_pending`` after a successful DB bill so a failed upsert
    does not permanently drop AnyTLS/Hy2/TUIC bytes.
    """

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
        return {}, {}, []

    name_map, plans = planned
    deltas_by_node: Dict[int, Dict[str, int]] = {}
    coefficient: Dict[int, float] = {}
    pending: list = []

    for plan in plans:
        client = client_for_node(_node_object(plan["id"], connect=False))
        if client is None:
            logger.info("sing-box transfer skipped node %s (no live channel)", plan["id"])
            continue
        try:
            # ``RPyCSingBoxClient.transfer`` never dials; a dead channel is {}.
            transfer = client.transfer()
        except Exception as exc:
            logger.warning("sing-box transfer read from node %s failed: %s", plan["id"], exc)
            transfer = None
        names = list((transfer or {}) or [])
        if not names:
            logger.info("sing-box transfer empty node %s", plan["id"])
            continue
        logger.info(
            "sing-box transfer node %s users=%d",
            plan["id"],
            len(names),
        )
        node_deltas, node_pending = deltas_from_transfer(
            plan["id"], transfer, _tracker
        )
        if node_pending:
            pending.append(node_pending)
        deltas_by_node[plan["id"]] = node_deltas
        coefficient[plan["id"]] = plan["coefficient"]

    return build_singbox_usage_params(deltas_by_node, name_map), coefficient, pending


def commit_singbox_pending(pending: list) -> None:
    for item in pending or []:
        _tracker.commit_pending(item)


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
