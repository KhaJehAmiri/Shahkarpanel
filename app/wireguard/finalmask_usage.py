"""Finalmask (Xray-native WireGuard) traffic collector.

Kernel ``wg show transfer`` does not see Finalmask peers (gVisor / no host
iface). Per-user billing therefore depends on Xray ``user>>>email>>>traffic``
counters — but only on cores that load peers as ``Users`` with email
(Xray ≥ 26.6 / UserManager PR). Those counters are **cumulative** when read
with ``reset=False``.

This module is the **authoritative** Finalmask path:

* Prefer RPyC loopback ``xray_users_transfer(reset=False)`` (survives public
  TLS API flaps on :62051).
* Convert cumulative totals to per-interval deltas (same contract as kernel WG
  and sing-box) so a failed poll never zeroes unread bytes.
* ``record_usages`` must **not** also call ``get_users_stats(reset=True)`` on
  the same Finalmask nodes — that would race this tracker and double-count.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from app.db import GetDB, crud
from app.wireguard.operations import _node_object
from app.wireguard.xray_native import xray_native_wg_enabled

logger = logging.getLogger("nexus-finalmask-usage")


class FinalmaskUsageTracker:
    """Cumulative ``user>>>email`` totals → per-interval deltas.

    Keyed by ``(node_id, email)``. First sighting baselines (delta 0). A drop
    means the core restarted / shard was replaced — treat current value as the
    delta for that interval.
    """

    def __init__(self):
        self._last: Dict[Tuple[int, str], int] = {}

    def deltas(self, node_id: int, transfer: Dict[str, dict]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for email, counters in (transfer or {}).items():
            try:
                total = int(counters.get("rx", 0)) + int(counters.get("tx", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            key = (int(node_id), str(email))
            last = self._last.get(key)
            self._last[key] = total
            if last is None:
                continue
            delta = total if total < last else total - last
            if delta > 0:
                out[str(email)] = delta
        return out

    def forget_node(self, node_id: int) -> None:
        nid = int(node_id)
        for key in [k for k in self._last if k[0] == nid]:
            del self._last[key]


_tracker = FinalmaskUsageTracker()


def _email_to_uid(email: str) -> Optional[int]:
    try:
        return int(str(email).split(".", 1)[0])
    except (TypeError, ValueError):
        return None


def build_finalmask_usage_params(
    deltas_by_node: Dict[int, Dict[str, int]],
) -> Dict[int, List[dict]]:
    result: Dict[int, List[dict]] = {}
    for node_id, email_deltas in deltas_by_node.items():
        agg: Dict[int, int] = defaultdict(int)
        for email, delta in email_deltas.items():
            uid = _email_to_uid(email)
            if uid is None or delta <= 0:
                continue
            agg[uid] += int(delta)
        result[node_id] = [{"uid": uid, "value": value} for uid, value in agg.items()]
    return result


def _read_transfer_via_rpyc(node, *, timeout: float = 8.0) -> Dict[str, dict]:
    """Cumulative per-email ``{rx, tx}`` via node-agent loopback StatsService."""
    if node is None:
        return {}
    remote = getattr(node, "remote", None)
    if remote is None:
        return {}
    try:
        # AttributeError → agent too old (no xray_users_transfer).
        if not hasattr(remote, "xray_users_transfer"):
            return {}
    except Exception:
        return {}

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        raw = pool.submit(remote.xray_users_transfer, False).result(timeout=timeout)
    except Exception as exc:
        logger.warning("Finalmask xray_users_transfer failed: %s", exc)
        return {}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return _normalize_transfer_payload(raw)


def _normalize_transfer_payload(raw) -> Dict[str, dict]:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
    elif isinstance(raw, dict):
        data = raw
    else:
        return {}
    return data if isinstance(data, dict) else {}


def _read_node_transfer(node_id: int) -> Dict[str, dict]:
    """Read cumulative Finalmask user counters; reconnect once if RPyC is dead."""
    from app import xray as xray_app

    node = xray_app.nodes.get(node_id) or _node_object(node_id, connect=False)
    transfer = _read_transfer_via_rpyc(node)
    if transfer:
        return transfer
    transfer = _read_transfer_via_grpc(node)
    if transfer:
        return transfer

    # RPyC often dies after competing one-shot connections / hot-replace.
    # One reconnect restores billing without waiting for the health job.
    try:
        live = xray_app.nodes.get(node_id)
        if live is not None:
            try:
                live.disconnect()
            except Exception:
                pass
            live.connect()
            node = live
        else:
            node = _node_object(node_id, connect=True)
    except Exception as exc:
        logger.debug(
            "Finalmask node %s reconnect for stats failed: %s", node_id, exc
        )
        node = None

    transfer = _read_transfer_via_rpyc(node)
    if transfer:
        return transfer
    return _read_transfer_via_grpc(node)


def _read_transfer_via_grpc(node, *, timeout: float = 15.0) -> Dict[str, dict]:
    """Fallback: public TLS Stats API with reset=False (cumulative)."""
    if node is None:
        return {}
    try:
        if hasattr(node, "ensure_api"):
            node.ensure_api(timeout=min(5.0, timeout), refresh=False)
    except Exception:
        pass
    api = getattr(node, "_api", None)
    if api is None:
        try:
            if hasattr(node, "ensure_api") and node.ensure_api(refresh=True, timeout=5):
                api = node.api
        except Exception:
            return {}
    if api is None:
        return {}
    try:
        down: dict[str, int] = defaultdict(int)
        up: dict[str, int] = defaultdict(int)
        for stat in api.get_users_stats(reset=False, timeout=int(timeout)):
            value = int(getattr(stat, "value", 0) or 0)
            if value <= 0:
                continue
            email = str(getattr(stat, "name", "") or "")
            link = getattr(stat, "link", None)
            if not email:
                continue
            if link == "uplink":
                up[email] += value
            else:
                down[email] += value
        out: Dict[str, dict] = {}
        for email in set(down) | set(up):
            rx, tx = down.get(email, 0), up.get(email, 0)
            if rx or tx:
                out[email] = {"rx": rx, "tx": tx}
        return out
    except Exception as exc:
        logger.warning("Finalmask gRPC cumulative stats failed: %s", exc)
        return {}


def collect_finalmask_usage_params(db=None) -> Tuple[Dict[int, List[dict]], Dict[int, float]]:
    """Return ``(api_params, usage_coefficient)`` deltas for Finalmask relays."""

    def _plan(session):
        nodes = crud.get_wireguard_nodes(session)
        plans = []
        for n in nodes or []:
            cfg = getattr(n, "wireguard", None)
            if not xray_native_wg_enabled(cfg):
                continue
            plans.append({"id": n.id, "coefficient": float(n.usage_coefficient or 1)})
        return plans

    if db is not None:
        plans = _plan(db)
    else:
        with GetDB() as session:
            plans = _plan(session)

    if not plans:
        return {}, {}

    deltas_by_node: Dict[int, Dict[str, int]] = {}
    coefficient: Dict[int, float] = {}

    for plan in plans:
        node_id = int(plan["id"])
        transfer = _read_node_transfer(node_id)
        if not transfer:
            continue
        email_deltas = _tracker.deltas(node_id, transfer)
        if not email_deltas:
            # Baseline-only cycle — still remember coefficient for merges.
            coefficient[node_id] = plan["coefficient"]
            continue
        deltas_by_node[node_id] = email_deltas
        coefficient[node_id] = plan["coefficient"]

    return build_finalmask_usage_params(deltas_by_node), coefficient


def merge_finalmask_usage(
    api_params: Dict[Optional[int], List[dict]],
    usage_coefficient: Dict[Optional[int], float],
    fm_params: Dict[int, List[dict]],
    fm_coefficient: Dict[int, float],
) -> None:
    for node_id, params in fm_params.items():
        if not params:
            continue
        api_params.setdefault(node_id, []).extend(params)
        usage_coefficient[node_id] = fm_coefficient.get(
            node_id, usage_coefficient.get(node_id, 1)
        )


def finalmask_node_ids(db=None) -> set:
    """Node ids that must be excluded from reset=True Xray stats polling."""

    def _ids(session):
        out = set()
        for n in crud.get_wireguard_nodes(session) or []:
            if xray_native_wg_enabled(getattr(n, "wireguard", None)):
                out.add(int(n.id))
        return out

    if db is not None:
        return _ids(db)
    with GetDB() as session:
        return _ids(session)


def flush_finalmask_node_stats(node_id: int) -> int:
    """Bank cumulative Finalmask user bytes before a shard rmi/restart.

    Returns bytes recorded. Clears the delta baseline afterward so a counter
    reset on the new shard does not look like a wraparound spike.
    """
    from app.jobs.record_usages import record_aggregated_user_usages

    node_id = int(node_id)
    transfer = _read_node_transfer(node_id)
    if not transfer:
        _tracker.forget_node(node_id)
        return 0
    email_deltas = _tracker.deltas(node_id, transfer)
    _tracker.forget_node(node_id)
    params_map = build_finalmask_usage_params({node_id: email_deltas})
    params = params_map.get(node_id) or []
    if not params:
        return 0
    coefficient = 1.0
    try:
        with GetDB() as db:
            n = crud.get_node_by_id(db, node_id)
            if n is not None:
                coefficient = float(n.usage_coefficient or 1)
    except Exception:
        pass
    record_aggregated_user_usages({node_id: params}, {node_id: coefficient})
    return sum(int(p.get("value") or 0) for p in params)
