"""Resumable WireGuard peer sync orchestrator (delta outbox + batch reconcile).

Hot path: ``enqueue_peer_change`` / ``schedule_resumable_sync`` writes outbox
rows and wakes per-node workers. Workers push small batches via
``wg_apply_batch`` so a dropped RPC resumes from the stored cursor instead of
restarting a multi-MB ``syncconf``.

Full reconcile (node connect, hash drift, admin force): stream peers ordered
by ``user_id`` in batches until ``cursor`` catches the desired set.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

from app.db import GetDB, crud
from app.db.models import NodeSyncCursor, PeerChangeOutbox
from app.wireguard.peer_cache import peer_cache
from app.wireguard.sync import WGUserPeer, amneziawg_enabled, plain_wg_enabled
from app.wireguard.transport import WireGuardTransportError, client_for_node

logger = logging.getLogger("shahkar-wg")

# Batch size for resumable full reconcile / outbox drain. Small enough for
# short RPyC timeouts; large enough to converge 500k peers in minutes.
WG_SYNC_BATCH_SIZE = 500
WG_SYNC_BATCH_TIMEOUT_SEC = 60
_OUTBOX_RETENTION = 50_000

_worker_lock = threading.Lock()
_workers_inflight: Dict[int, bool] = {}
_wake_event = threading.Event()
_scheduler_started = False
_global_generation = 0
_generation_lock = threading.Lock()
# Per-node locks so one flaky relay does not serialize the whole fleet.
# A small semaphore caps concurrent hot-replaces (CPU + RPyC pressure).
_finalmask_node_locks: Dict[int, threading.Lock] = {}
_finalmask_node_locks_guard = threading.Lock()
# Keep fleet-wide hot-replace pressure low: each call can hold RPyC for
# minutes on large shards; overlapping with health probes kills the session.
_finalmask_concurrency = threading.Semaphore(2)
_node_cooldown_until: Dict[int, float] = {}
_node_fail_streak: Dict[int, int] = {}
_NODE_COOLDOWN_FAIL_SEC = 30.0
_NODE_COOLDOWN_FAIL_MAX_SEC = 180.0
_NODE_COOLDOWN_OK_SEC = 1.0
# Nodes currently inside a Finalmask hot-replace (health check must not
# preempt their RPyC session with connect_node).
_finalmask_rpc_busy: Dict[int, int] = {}


def _finalmask_lock_for(node_id: int) -> threading.Lock:
    with _finalmask_node_locks_guard:
        lock = _finalmask_node_locks.get(int(node_id))
        if lock is None:
            lock = threading.Lock()
            _finalmask_node_locks[int(node_id)] = lock
        return lock


def mark_finalmask_rpc_busy(node_id: int, busy: bool) -> None:
    """Health / connect paths skip preempting a node while this is set.

    Used for Finalmask hot-replace *and* ordinary WG RPyC applies — any long
    panel→node RPC that must not be killed by a concurrent ``connect_node``.
    """
    nid = int(node_id)
    with _finalmask_node_locks_guard:
        if busy:
            _finalmask_rpc_busy[nid] = int(_finalmask_rpc_busy.get(nid, 0)) + 1
        else:
            left = int(_finalmask_rpc_busy.get(nid, 0)) - 1
            if left <= 0:
                _finalmask_rpc_busy.pop(nid, None)
            else:
                _finalmask_rpc_busy[nid] = left


def is_finalmask_rpc_busy(node_id: int) -> bool:
    with _finalmask_node_locks_guard:
        return int(_finalmask_rpc_busy.get(int(node_id), 0)) > 0


# Aliases — prefer these names for non-Finalmask callers.
mark_node_rpc_busy = mark_finalmask_rpc_busy
is_node_rpc_busy = is_finalmask_rpc_busy



def _set_node_cooldown(node_id: int, seconds: float) -> None:
    with _worker_lock:
        _node_cooldown_until[int(node_id)] = time.monotonic() + max(0.0, float(seconds))


def _node_on_cooldown(node_id: int) -> bool:
    with _worker_lock:
        until = _node_cooldown_until.get(int(node_id), 0.0)
    return time.monotonic() < until


def _note_node_failure(node_id: int) -> float:
    """Exponential backoff after a failed apply; never advances the cursor."""
    with _worker_lock:
        streak = int(_node_fail_streak.get(int(node_id), 0)) + 1
        _node_fail_streak[int(node_id)] = streak
    delay = min(
        _NODE_COOLDOWN_FAIL_MAX_SEC,
        _NODE_COOLDOWN_FAIL_SEC * (2 ** min(streak - 1, 3)),
    )
    _set_node_cooldown(int(node_id), delay)
    return delay


def _note_node_success(node_id: int) -> None:
    with _worker_lock:
        _node_fail_streak[int(node_id)] = 0
    _set_node_cooldown(int(node_id), _NODE_COOLDOWN_OK_SEC)


_generation_seeded = False


def _seed_generation_from_db() -> None:
    """After panel restart, in-memory gen is 0 — lift it to the DB watermark."""
    global _global_generation, _generation_seeded
    if _generation_seeded:
        return
    try:
        with GetDB() as db:
            mx = db.query(NodeSyncCursor.generation).order_by(
                NodeSyncCursor.generation.desc()
            ).limit(1).scalar()
        if mx is not None:
            with _generation_lock:
                if int(mx) > int(_global_generation):
                    _global_generation = int(mx)
        _generation_seeded = True
    except Exception:
        logger.debug("generation seed from DB failed", exc_info=True)


def bump_generation() -> int:
    global _global_generation
    _seed_generation_from_db()
    with _generation_lock:
        _global_generation += 1
        return _global_generation


def current_generation() -> int:
    with _generation_lock:
        return _global_generation


def peers_content_hash(peers: Sequence[WGUserPeer]) -> str:
    """Stable hash of the desired active peer set (pubkey + address + slot)."""
    parts = []
    for p in sorted(peers, key=lambda x: (x.user_id, x.public_key)):
        if not p.active:
            continue
        parts.append(
            f"{p.user_id}:{p.public_key}:{p.address}:{p.awg_address}:"
            f"{p.preshared_key or ''}:{p.finalmask_slot}"
        )
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest


def _peer_to_batch_row(peer: WGUserPeer, *, stack: str = "plain") -> Optional[dict]:
    """Serialize a peer for ``wg_apply_batch`` (one interface stack)."""
    if stack == "awg":
        addr = peer.awg_address
    else:
        addr = peer.address
    if not peer.public_key:
        return None
    if peer.active and not addr:
        return None
    allowed = ""
    if addr:
        raw = addr.split("/")[0]
        allowed = f"{raw}/32"
    return {
        "public_key": peer.public_key,
        "allowed_ips": allowed,
        "preshared_key": peer.preshared_key,
        "active": bool(peer.active and allowed),
        "user_id": int(peer.user_id),
    }


def enqueue_peer_change(
    *,
    op: str,
    user_id: Optional[int] = None,
    public_key: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    """Append a delta to the outbox and wake sync workers."""
    with GetDB() as db:
        row = PeerChangeOutbox(
            op=op,
            user_id=user_id,
            public_key=public_key,
            payload=payload,
        )
        db.add(row)
        db.commit()
    bump_generation()
    peer_cache.invalidate()
    _ensure_scheduler()
    _wake_event.set()


def enqueue_full_reconcile(*, reason: str = "manual") -> None:
    """Mark every WG node for a resumable full reconcile from cursor 0."""
    peers = peer_cache.get_peers()
    desired = peers_content_hash(peers)
    gen = bump_generation()
    peer_cache.invalidate()
    with GetDB() as db:
        nodes = crud.get_wireguard_nodes(db)
        for n in nodes:
            cur = db.get(NodeSyncCursor, n.id)
            if cur is None:
                cur = NodeSyncCursor(node_id=n.id)
                db.add(cur)
            cur.generation = gen
            cur.cursor_user_id = 0
            cur.desired_hash = desired
            cur.status = "pending"
            cur.peers_done = 0
            cur.peers_total = sum(1 for p in peers if p.active)
            cur.error = None
        db.commit()
    logger.info(
        "WG full reconcile queued reason=%s generation=%s peers=%s nodes=%s",
        reason,
        gen,
        sum(1 for p in peers if p.active),
        len(nodes) if nodes else 0,
    )
    _ensure_scheduler()
    _wake_event.set()


def schedule_resumable_sync() -> None:
    """Hot-path entry: invalidate cache, ensure cursors pending, wake workers.

    Replaces the old ``sync_all_nodes`` full ``syncconf`` push on every user
    touch. Finalmask still has its own debounce path.
    """
    # Allocate any missing autoscale peers before hashing/pushing — bulk
    # Proxy(WireGuard) inserts otherwise leave users offline until a manual
    # ensure_all_peers / subscription touch.
    try:
        from app.wireguard.wg_manager import autoscale_enabled, ensure_all_peers

        if autoscale_enabled():
            with GetDB() as db:
                created = ensure_all_peers(db)
                if created:
                    db.commit()
                    logger.info("resumable sync: ensure_all_peers created=%s", created)
                else:
                    db.rollback()
    except Exception:
        logger.exception("resumable sync: ensure_all_peers failed")

    peer_cache.invalidate()
    gen = bump_generation()
    peers = peer_cache.get_peers()
    desired = peers_content_hash(peers)
    active_n = sum(1 for p in peers if p.active)
    # Catch-all outbox marker so nodes that only drain deltas still notice.
    with GetDB() as db:
        try:
            from app.wireguard.capacity import guard_fleet_subnet_capacity

            guard_fleet_subnet_capacity(db, active_peers=active_n)
        except Exception:
            logger.exception("fleet subnet capacity guard failed")
        db.add(
            PeerChangeOutbox(
                op="reconcile_hint",
                user_id=None,
                public_key=None,
                payload={"generation": gen, "desired_hash": desired},
            )
        )
        nodes = crud.get_wireguard_nodes(db) or []
        from app.wireguard.xray_native import xray_native_wg_enabled

        for n in nodes:
            cur = db.get(NodeSyncCursor, n.id)
            if cur is None:
                cur = NodeSyncCursor(node_id=n.id)
                db.add(cur)
            had_generation = bool(cur.generation)
            cur.desired_hash = desired
            cur.peers_total = active_n
            cur.error = None
            # Finalmask membership changes are applied by the dirty-slot
            # reload path. Rewinding every converged node to slot 0 on each
            # user add stampedes the fleet (RPyC storms → connect flaps).
            if xray_native_wg_enabled(getattr(n, "wireguard", None)):
                if cur.status == "converged":
                    cur.generation = gen
                    continue
                if cur.status == "error" or not had_generation:
                    cur.cursor_user_id = 0
                    cur.peers_done = 0
                cur.generation = gen
                if cur.status != "running":
                    cur.status = "pending"
                continue
            # Kernel WG / AWG: never rewind a mid-flight cursor; only restart
            # a full pass after converge/error (or enqueue_full_reconcile).
            if cur.status in ("converged", "error") or not had_generation:
                cur.cursor_user_id = 0
                cur.peers_done = 0
            cur.generation = gen
            if cur.status != "running":
                cur.status = "pending"
        # Trim old outbox rows
        cutoff = (
            db.query(PeerChangeOutbox.id)
            .order_by(PeerChangeOutbox.id.desc())
            .offset(_OUTBOX_RETENTION)
            .limit(1)
            .scalar()
        )
        if cutoff:
            db.query(PeerChangeOutbox).filter(PeerChangeOutbox.id < int(cutoff)).delete(
                synchronize_session=False
            )
        db.commit()
    _ensure_scheduler()
    _wake_event.set()


def on_node_connected(node_id: int) -> None:
    """Resume or start reconcile after a node channel comes back."""
    try:
        from app.wireguard.finalmask_reload import clear_agent_hot_cache

        clear_agent_hot_cache(int(node_id))
    except Exception:
        pass
    with GetDB() as db:
        cur = db.get(NodeSyncCursor, int(node_id))
        if cur is None:
            cur = NodeSyncCursor(node_id=int(node_id))
            db.add(cur)
        if cur.status in ("paused", "error", "converged", "pending"):
            # Resume from stored cursor when generation matches desired set.
            cur.status = "pending"
            if not cur.generation:
                cur.generation = current_generation() or bump_generation()
                cur.cursor_user_id = 0
        db.commit()
    _ensure_scheduler()
    _wake_event.set()


def _interfaces_for_node(db, dbnode) -> List[tuple]:
    """Return ``[(interface, stack), ...]`` for batch apply."""
    cfg = getattr(dbnode, "wireguard", None)
    if cfg is None:
        return []
    from app.tunnel.relay import node_delegates_wireguard_to_tunnel
    from app.wireguard.wg_manager import autoscale_enabled

    out = []
    tunnel = False
    try:
        tunnel = bool(node_delegates_wireguard_to_tunnel(db, dbnode.id))
    except Exception:
        tunnel = False
    if plain_wg_enabled(cfg) and cfg.interface and not autoscale_enabled() and not tunnel:
        out.append((cfg.interface, "plain"))
    if amneziawg_enabled(cfg) and cfg.awg_interface:
        out.append((cfg.awg_interface, "awg"))
    return out


def _get_client(node_id: int):
    from app.wireguard.operations import _node_object

    return client_for_node(_node_object(int(node_id), connect=True))


def _apply_batch(
    client,
    *,
    interface: str,
    generation: int,
    cursor: int,
    peers: List[dict],
    removes: List[str],
) -> dict:
    if not hasattr(client, "apply_batch"):
        raise WireGuardTransportError("node agent does not support wg_apply_batch")
    return client.apply_batch(
        interface=interface,
        generation=generation,
        cursor=cursor,
        peers=peers,
        removes=removes,
        timeout=WG_SYNC_BATCH_TIMEOUT_SEC,
    )


def _sync_status(client) -> dict:
    if not hasattr(client, "sync_status"):
        return {}
    try:
        return client.sync_status(timeout=15) or {}
    except Exception:
        return {}


def _run_node_worker(node_id: int) -> None:
    try:
        _sync_one_node(int(node_id))
    except Exception:
        logger.exception("WG sync worker failed for node %s", node_id)
        delay = _note_node_failure(int(node_id))
        with GetDB() as db:
            cur = db.get(NodeSyncCursor, int(node_id))
            if cur is not None:
                cur.status = "paused"
                cur.error = f"worker exception (retry in {int(delay)}s)"
                db.commit()
    finally:
        with _worker_lock:
            _workers_inflight[int(node_id)] = False



def _sync_finalmask_node(node_id: int, *, generation: int, cursor: int) -> None:
    """Resumable Finalmask shard hot-replace (cursor = next slot to apply)."""
    from app.wireguard.finalmask_reload import (
        _commit_fingerprints,
        hot_replace_finalmask_shards,
    )
    from app.wireguard.finalmask_shard import group_peers_by_slot
    from app.wireguard.xray_native import xray_native_wg_enabled

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if dbnode is None:
            return
        if not xray_native_wg_enabled(getattr(dbnode, "wireguard", None)):
            # Not a Finalmask node. Tunnel exits still need kernel WG peers —
            # never mark them converged with peers_done=0 (that left exits
            # empty after every agent recreate / panel reconnect).
            from app.tunnel.relay import node_is_tunnel_exit
            from app.wireguard.operations import sync_node

            cur = db.get(NodeSyncCursor, node_id)
            try:
                is_exit = bool(node_is_tunnel_exit(db, node_id))
            except Exception:
                is_exit = False
            if is_exit:
                # Chunked apply_specs (transport) pushes WgInterface peers
                # automatically — never mark converged with peers_done=0.
                ok = False
                try:
                    ok = bool(sync_node(db, dbnode))
                except Exception as exc:
                    logger.warning(
                        "Tunnel-exit WG sync node=%s failed: %s", node_id, exc,
                    )
                    delay = _note_node_failure(int(node_id))
                    if cur is not None:
                        cur.status = "paused"
                        cur.error = f"tunnel-exit sync: {exc}"[:500]
                        db.commit()
                    logger.info(
                        "Tunnel-exit node=%s will retry in %ss", node_id, int(delay),
                    )
                    return
                if cur is not None:
                    from app.db.models import WgInterface, WgPeer

                    peer_n = (
                        db.query(WgPeer)
                        .join(WgInterface, WgPeer.interface_id == WgInterface.id)
                        .filter(WgInterface.node_id == node_id)
                        .count()
                    )
                    cur.status = "converged" if ok else "paused"
                    cur.peers_done = int(peer_n) if ok else int(cur.peers_done or 0)
                    cur.peers_total = int(peer_n)
                    cur.applied_hash = cur.desired_hash if ok else ""
                    cur.error = None if ok else "tunnel-exit apply_specs failed"
                    if ok:
                        _set_node_cooldown(int(node_id), _NODE_COOLDOWN_OK_SEC)
                        with _worker_lock:
                            _node_fail_streak.pop(int(node_id), None)
                    else:
                        _note_node_failure(int(node_id))
                    db.commit()
                return
            if cur is not None:
                cur.status = "converged"
                cur.applied_hash = cur.desired_hash
                cur.error = None
                db.commit()
            return

    peers = peer_cache.get_peers()
    by_slot = group_peers_by_slot(peers)
    slots = sorted(by_slot.keys())
    desired = peers_content_hash(peers)
    total_peers = sum(1 for p in peers if p.active)

    # cursor_user_id = next Finalmask slot to apply (0 = start at shard 0).
    pending = [s for s in slots if int(s) >= int(cursor or 0)]
    if not pending:
        with GetDB() as db:
            cur = db.get(NodeSyncCursor, node_id)
            if cur is not None:
                cur.status = "converged"
                cur.peers_done = total_peers
                cur.peers_total = total_peers
                cur.desired_hash = desired
                cur.applied_hash = desired
                cur.error = None
                db.commit()
        return

    # One shard per wake keeps RPyC payloads small on flaky Iran↔abroad links
    # and makes resume precise. Per-node lock + capped concurrency so a single
    # slow node cannot stall the rest of the fleet.
    BATCH_SLOTS = 1
    chunk = pending[:BATCH_SLOTS]
    try:
        with _finalmask_concurrency:
            with _finalmask_lock_for(node_id):
                mark_finalmask_rpc_busy(node_id, True)
                try:
                    ok = hot_replace_finalmask_shards(
                        node_id,
                        set(chunk),
                        peers=peers,
                        skip_address_ensure=True,
                    )
                finally:
                    mark_finalmask_rpc_busy(node_id, False)
    except Exception as exc:
        delay = _note_node_failure(node_id)
        logger.warning(
            "Finalmask batch node=%s slots=%s failed: %s (retry in %ss)",
            node_id, chunk, exc, int(delay),
        )
        with GetDB() as db:
            cur = db.get(NodeSyncCursor, node_id)
            if cur is not None:
                # Keep cursor — never skip a failed shard.
                cur.status = "paused"
                cur.error = f"{exc} (retry in {int(delay)}s)"[:500]
                db.commit()
        return

    if not ok:
        # Permanent capability gap: agent has no hot-replace RPC. One full
        # restart converges every shard; spinning on cursor=0 never serves
        # newly allocated peers (reseller WG "configs exist but offline").
        agent_missing_hot = False
        try:
            from app import xray as xray_pkg

            node_obj = xray_pkg.nodes.get(int(node_id))
            remote = getattr(node_obj, "remote", None) if node_obj else None
            agent_missing_hot = bool(
                remote is not None
                and not hasattr(remote, "xray_hot_replace_inbounds_json")
            )
        except Exception:
            agent_missing_hot = False

        if agent_missing_hot:
            try:
                from app.wireguard.finalmask_reload import (
                    _full_restart_allowed,
                    _note_full_restart,
                    _cooldown_left,
                    _mark_agent_hot_unsupported,
                )

                _mark_agent_hot_unsupported(int(node_id))
                if not _full_restart_allowed(int(node_id)):
                    delay = max(30.0, _cooldown_left(int(node_id)))
                    logger.warning(
                        "Finalmask node=%s: agent lacks hot-replace; "
                        "deferring full restart (cooldown %.0fs left)",
                        node_id,
                        delay,
                    )
                    _note_node_failure(node_id)  # back off this node briefly
                    with GetDB() as db:
                        cur = db.get(NodeSyncCursor, node_id)
                        if cur is not None:
                            cur.status = "paused"
                            cur.error = (
                                f"hot-replace unsupported; restart cooldown "
                                f"{int(delay)}s"
                            )[:500]
                            db.commit()
                    return
            except Exception:
                pass
            logger.warning(
                "Finalmask node=%s: agent lacks hot-replace; full Xray restart "
                "(cooldown gate)",
                node_id,
            )
            try:
                from app.xray.operations import restart_node
                from app.wireguard.finalmask_reload import _note_full_restart

                _note_full_restart(int(node_id))
                restart_node(int(node_id))
            except Exception as exc:
                delay = _note_node_failure(node_id)
                with GetDB() as db:
                    cur = db.get(NodeSyncCursor, node_id)
                    if cur is not None:
                        cur.status = "paused"
                        cur.error = f"restart fallback failed: {exc}"[:500]
                        db.commit()
                return
            _note_node_success(node_id)
            with GetDB() as db:
                cur = db.get(NodeSyncCursor, node_id)
                if cur is not None:
                    max_slot = max((int(s) for s in slots), default=-1)
                    cur.cursor_user_id = max_slot + 1
                    cur.peers_done = total_peers
                    cur.peers_total = total_peers
                    cur.desired_hash = desired
                    cur.applied_hash = desired
                    cur.status = "ok"
                    cur.error = None
                    db.commit()
            return

        delay = _note_node_failure(node_id)
        with GetDB() as db:
            cur = db.get(NodeSyncCursor, node_id)
            if cur is not None:
                cur.status = "paused"
                cur.error = (
                    f"finalmask hot-replace failed slots={chunk} "
                    f"(retry in {int(delay)}s)"
                )[:500]
                db.commit()
        logger.warning(
            "Finalmask node=%s slots=%s hot-replace failed; holding cursor=%s",
            node_id, chunk, cursor,
        )
        return

    last_done = int(chunk[-1])
    new_cursor = last_done + 1  # next slot
    done_peers = sum(
        1 for s, plist in by_slot.items() if int(s) <= last_done
        for p in plist if getattr(p, "active", False)
    )
    more = any(int(s) >= new_cursor for s in slots)
    _note_node_success(node_id)
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        cur = db.get(NodeSyncCursor, node_id)
        if cur is None:
            return
        # Generation may bump while we fly (new users). Keep the cursor — do
        # not restart from slot 0 or a growing fleet never converges.
        live_gen = int(cur.generation or 0)
        cur.cursor_user_id = new_cursor
        cur.peers_done = done_peers
        cur.peers_total = total_peers
        cur.desired_hash = desired
        cur.error = None
        if more:
            cur.status = "pending"
        else:
            # Finished every shard. New users that arrived mid-flight land in
            # sticky slots via ensure_finalmask_slots and are applied by the
            # dirty-slot Finalmask reload path — do NOT rewind to slot 0 or a
            # growing fleet thrash-rescans forever.
            cur.status = "converged"
            cur.applied_hash = desired
            if live_gen > generation:
                logger.info(
                    "Finalmask node=%s converged after pass gen=%s (live gen=%s); "
                    "incremental dirty-slot reload will catch mid-flight adds",
                    node_id, generation, live_gen,
                )
            try:
                _commit_fingerprints(node_id, db, dbnode, peers)
            except Exception:
                logger.debug("finalmask fingerprint commit failed", exc_info=True)
            try:
                from app.wireguard.finalmask_reload import schedule_finalmask_xray_reload

                schedule_finalmask_xray_reload(bulk=False)
            except Exception:
                logger.debug("finalmask post-converge reload schedule failed", exc_info=True)
        db.commit()
    logger.info(
        "Finalmask sync node=%s slots=%s cursor=%s done_peers=%s/%s more=%s",
        node_id, chunk, new_cursor, done_peers, total_peers, more,
    )
    # Wake for remaining slots.
    _wake_event.set()


def _sync_one_node(node_id: int) -> None:
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if dbnode is None or dbnode.wireguard is None:
            return
        cur = db.get(NodeSyncCursor, node_id)
        if cur is None:
            cur = NodeSyncCursor(node_id=node_id, status="pending")
            db.add(cur)
            db.commit()
            db.refresh(cur)
        if cur.status == "converged" and not _pending_outbox(db, cur.last_outbox_id):
            return
        cur.status = "running"
        db.commit()
        generation = int(cur.generation or 0)
        cursor = int(cur.cursor_user_id or 0)
        last_outbox = int(cur.last_outbox_id or 0)
        ifaces = list(_interfaces_for_node(db, dbnode))

    if not ifaces:
        # Finalmask-only / tunnel / autoscale — drive Finalmask shard batches.
        _sync_finalmask_node(node_id, generation=generation, cursor=cursor)
        return

    client = _get_client(node_id)
    if client is None:
        with GetDB() as db:
            cur = db.get(NodeSyncCursor, node_id)
            if cur is not None:
                cur.status = "paused"
                cur.error = "node not connected"
                db.commit()
        return

    # Bootstrap: ensure interfaces exist via one lightweight full apply of the
    # empty/current set only when the node reports no sync state yet.
    try:
        st = _sync_status(client)
        needs_bootstrap = not st
    except Exception:
        needs_bootstrap = True
    if needs_bootstrap:
        try:
            from app.wireguard.sync import build_node_specs

            with GetDB() as db:
                dbnode = crud.get_node_by_id(db, node_id)
                cfg = dbnode.wireguard if dbnode else None
            if cfg is not None and hasattr(client, "apply_specs"):
                # Bring interfaces up with zero peers; batches fill membership.
                specs = build_node_specs(cfg, [])
                if specs:
                    client.apply_specs(specs, timeout=120)
        except Exception as exc:
            logger.warning("WG bootstrap empty-spec node=%s failed: %s", node_id, exc)

    # Prefer draining outbox deltas when mid-reconcile is not required.
    drained = _drain_outbox(client, node_id, ifaces, last_outbox)
    if drained is not None:
        last_outbox = drained

    peers = [p for p in peer_cache.get_peers() if p.active or True]
    active_peers = sorted(peers, key=lambda p: p.user_id)
    desired = peers_content_hash(active_peers)
    total = sum(1 for p in active_peers if p.active)

    # Stream batches from cursor until done.
    while True:
        batch_peers = [
            p for p in active_peers
            if int(p.user_id) > cursor
        ][:WG_SYNC_BATCH_SIZE]
        if not batch_peers:
            break
        next_cursor = int(batch_peers[-1].user_id)
        try:
            for iface, stack in ifaces:
                rows = []
                removes = []
                for p in batch_peers:
                    row = _peer_to_batch_row(p, stack=stack)
                    if row is None:
                        continue
                    if not row["active"]:
                        removes.append(row["public_key"])
                    else:
                        rows.append(row)
                _apply_batch(
                    client,
                    interface=iface,
                    generation=generation,
                    cursor=next_cursor,
                    peers=rows,
                    removes=removes,
                )
        except Exception as exc:
            logger.warning(
                "WG batch apply node=%s cursor=%s failed: %s — will resume",
                node_id,
                cursor,
                exc,
            )
            with GetDB() as db:
                cur = db.get(NodeSyncCursor, node_id)
                if cur is not None:
                    cur.status = "paused"
                    cur.cursor_user_id = cursor
                    cur.last_outbox_id = last_outbox
                    cur.desired_hash = desired
                    cur.peers_total = total
                    cur.error = str(exc)[:500]
                    db.commit()
            return

        cursor = next_cursor
        done = sum(1 for p in active_peers if int(p.user_id) <= cursor)
        with GetDB() as db:
            cur = db.get(NodeSyncCursor, node_id)
            if cur is None:
                return
            # Keep cursor across generation bumps (continuous user growth).
            cur.cursor_user_id = cursor
            cur.peers_done = done
            cur.peers_total = total
            cur.last_outbox_id = last_outbox
            cur.desired_hash = desired
            cur.status = "running"
            cur.error = None
            db.commit()
        logger.info(
            "WG sync node=%s progress=%s/%s cursor=%s generation=%s",
            node_id,
            done,
            total,
            cursor,
            generation,
        )

    # Converged: optionally ask node for status hash.
    status = _sync_status(client)
    applied = (status.get("hash") if isinstance(status, dict) else None) or desired
    with GetDB() as db:
        cur = db.get(NodeSyncCursor, node_id)
        if cur is not None:
            cur.status = "converged"
            cur.cursor_user_id = cursor
            cur.peers_done = total
            cur.peers_total = total
            cur.desired_hash = desired
            cur.applied_hash = str(applied)[:64]
            cur.last_outbox_id = last_outbox
            cur.error = None
            db.commit()
    logger.info("WG sync node=%s converged peers=%s generation=%s", node_id, total, generation)


def _pending_outbox(db, last_id: int) -> bool:
    q = db.query(PeerChangeOutbox.id).filter(PeerChangeOutbox.id > int(last_id or 0))
    return db.query(q.exists()).scalar()


def _drain_outbox(client, node_id: int, ifaces: List[tuple], last_outbox: int) -> Optional[int]:
    """Apply pending outbox deltas; return new last_outbox_id or None."""
    with GetDB() as db:
        rows = (
            db.query(PeerChangeOutbox)
            .filter(PeerChangeOutbox.id > int(last_outbox or 0))
            .order_by(PeerChangeOutbox.id.asc())
            .limit(WG_SYNC_BATCH_SIZE)
            .all()
        )
        if not rows:
            return last_outbox
        payload_rows = [
            {
                "id": r.id,
                "op": r.op,
                "user_id": r.user_id,
                "public_key": r.public_key,
                "payload": r.payload or {},
            }
            for r in rows
        ]
        new_last = int(rows[-1].id)

    peers_upsert: List[dict] = []
    removes: List[str] = []
    for r in payload_rows:
        op = r["op"]
        if op == "reconcile_hint":
            continue
        pk = r.get("public_key") or (r.get("payload") or {}).get("public_key")
        if op in ("remove", "disable") and pk:
            removes.append(pk)
            continue
        if op == "upsert":
            pl = r.get("payload") or {}
            if not pk:
                continue
            peers_upsert.append(
                {
                    "public_key": pk,
                    "allowed_ips": pl.get("allowed_ips") or "",
                    "preshared_key": pl.get("preshared_key"),
                    "active": bool(pl.get("active", True)),
                    "user_id": r.get("user_id"),
                }
            )

    if not peers_upsert and not removes:
        return new_last

    try:
        for iface, _stack in ifaces:
            # For delta we apply the same keys to each iface; allowed_ips from
            # payload should already match the stack when enqueued.
            _apply_batch(
                client,
                interface=iface,
                generation=current_generation(),
                cursor=new_last,
                peers=peers_upsert,
                removes=removes,
            )
    except Exception as exc:
        logger.warning("WG outbox drain node=%s failed: %s", node_id, exc)
        raise

    with GetDB() as db:
        cur = db.get(NodeSyncCursor, node_id)
        if cur is not None:
            cur.last_outbox_id = new_last
            db.commit()
    return new_last


def _scheduler_loop() -> None:
    while True:
        _wake_event.wait(timeout=5.0)
        _wake_event.clear()
        try:
            with GetDB() as db:
                pending = (
                    db.query(NodeSyncCursor.node_id)
                    .filter(NodeSyncCursor.status.in_(("pending", "paused", "running")))
                    .all()
                )
                # Also pick nodes with no cursor yet.
                node_ids = {int(r[0]) for r in pending}
                for n in crud.get_wireguard_nodes(db) or []:
                    cur = db.get(NodeSyncCursor, n.id)
                    if cur is None:
                        node_ids.add(int(n.id))
                    elif cur.status in ("pending", "paused"):
                        node_ids.add(int(n.id))
        except Exception:
            logger.exception("WG sync scheduler listing failed")
            time.sleep(2)
            continue

        for nid in node_ids:
            if _node_on_cooldown(nid):
                continue
            with _worker_lock:
                if _workers_inflight.get(nid):
                    continue
                _workers_inflight[nid] = True
            t = threading.Thread(
                target=_run_node_worker,
                args=(nid,),
                name=f"wg-sync-{nid}",
                daemon=True,
            )
            t.start()


def _ensure_scheduler() -> None:
    global _scheduler_started
    with _worker_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    _seed_generation_from_db()
    t = threading.Thread(target=_scheduler_loop, name="wg-sync-scheduler", daemon=True)
    t.start()
    logger.info(
        "WireGuard resumable sync scheduler started (generation=%s)",
        current_generation(),
    )


def sync_progress() -> List[dict]:
    """Snapshot of per-node sync progress for admin/API."""
    with GetDB() as db:
        rows = db.query(NodeSyncCursor).all()
        return [
            {
                "node_id": r.node_id,
                "generation": r.generation,
                "cursor_user_id": r.cursor_user_id,
                "status": r.status,
                "peers_done": r.peers_done,
                "peers_total": r.peers_total,
                "desired_hash": r.desired_hash,
                "applied_hash": r.applied_hash,
                "error": r.error,
            }
            for r in rows
        ]
