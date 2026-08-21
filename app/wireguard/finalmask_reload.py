"""Debounced Finalmask (Xray-native WG) peer reload — shard-scoped hot replace.

Kernel WireGuard peers update via ``wg syncconf`` on every user change, but
Finalmask peers are baked into Xray inbound ``settings.peers``. Xray-core has
no AlterInbound peer ops for WireGuard, so membership changes used to call
``restart_node()`` and drop the entire Reality tunnel.

With sharding (``app/wireguard/finalmask_shard.py``) each slot is its own
inbound. On peer churn we:

1. Fingerprint **active** peers per shard (inactive users are not baked).
2. Hot-replace only the changed shard inbound(s) via the node agent's
   ``xray api rmi`` + ``adi`` path (no full core restart).
3. Fall back to ``restart_node`` only when structure changed (listen base /
   keys / noise / MTU / tunnel outbound) or hot replace fails.

Call ``schedule_finalmask_xray_reload`` after peer membership changes. Rapid
bursts coalesce; bulk ops use a longer debounce so one swap covers many diffs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

_agent_hot_ok: Dict[int, bool] = {}
_agent_hot_checked_at: Dict[int, float] = {}
_last_full_restart_at: Dict[int, float] = {}

# Old agents without hot-replace used to full-restart Xray on every peer churn
# (dozens/hour), killing RPyC + tunnel relay until a manual reconnect. Cap that.
FULL_RESTART_COOLDOWN_SEC = 600.0
# Re-probe "unsupported" cache periodically so a manual agent upgrade is picked up.
HOT_UNSUPPORTED_REPROBE_SEC = 1800.0


def clear_agent_hot_cache(node_id: Optional[int] = None) -> None:
    """Forget hot-replace capability (call after agent upgrade / reconnect)."""
    if node_id is None:
        _agent_hot_ok.clear()
        _agent_hot_checked_at.clear()
        return
    nid = int(node_id)
    _agent_hot_ok.pop(nid, None)
    _agent_hot_checked_at.pop(nid, None)


def _node_supports_hot_replace(node_id: int) -> bool:
    """Cache whether the connected agent exposes Finalmask hot-replace RPC."""
    nid = int(node_id)
    now = time.time()
    cached = _agent_hot_ok.get(nid)
    checked = _agent_hot_checked_at.get(nid, 0.0)
    if cached is True:
        return True
    if cached is False and (now - checked) < HOT_UNSUPPORTED_REPROBE_SEC:
        return False
    try:
        from app import xray as xray_pkg

        node_obj = xray_pkg.nodes.get(nid)
        if node_obj is None or not getattr(node_obj, "connected", False):
            return True  # unknown — try hot first
        conn = getattr(node_obj, "connection", None)
        root = getattr(conn, "root", None) if conn is not None else None
        # ``dir(root)`` lists exposed RPyC methods; bare hasattr lies on netrefs.
        ok = bool(root is not None and "xray_hot_replace_inbounds_json" in dir(root))
        _agent_hot_ok[nid] = ok
        _agent_hot_checked_at[nid] = now
        return ok
    except Exception:
        return True


def _mark_agent_hot_unsupported(node_id: int) -> None:
    nid = int(node_id)
    _agent_hot_ok[nid] = False
    _agent_hot_checked_at[nid] = time.time()


def _node_backoff_left(node_id: int) -> float:
    """Seconds left on a node's connect backoff; 0 when it can take an apply.

    A node in backoff cannot accept a hot-replace, and counting that as an
    apply failure keeps every dirty slot pending forever — one dead relay then
    stops new peers from landing on the healthy nodes too, and the retry timer
    below spins hard enough to starve the usage collector of RPyC calls. The
    node reconciles from its own cursor via ``on_node_connected`` when it comes
    back, so skipping it here loses nothing.
    """
    try:
        from app import xray as xray_pkg

        node_obj = xray_pkg.nodes.get(int(node_id))
        if node_obj is None or getattr(node_obj, "connected", False):
            return 0.0
        nxt = float(getattr(node_obj, "_next_connect_attempt", 0.0) or 0.0)
        return max(0.0, nxt - time.time())
    except Exception:
        return 0.0


def _full_restart_allowed(node_id: int) -> bool:
    last = _last_full_restart_at.get(int(node_id), 0.0)
    return (time.time() - last) >= FULL_RESTART_COOLDOWN_SEC


def _note_full_restart(node_id: int) -> None:
    _last_full_restart_at[int(node_id)] = time.time()


def _cooldown_left(node_id: int) -> float:
    last = _last_full_restart_at.get(int(node_id), 0.0)
    return max(0.0, FULL_RESTART_COOLDOWN_SEC - (time.time() - last))


# Use uvicorn's error logger so Finalmask reload lines show in panel docker logs
# (the dedicated shahkar-wg logger is often unconfigured and silent).
logger = logging.getLogger("uvicorn.error")

DEFAULT_DEBOUNCE_SEC = 0.25
BULK_DEBOUNCE_SEC = 2.0
# Heuristic: if this many shard fingerprints differ at once, prefer the longer
# coalesce window so a bulk enable lands as one hot-replace per touched shard.
BULK_DIFF_THRESHOLD = 3
# Only fall back to a full-core restart when *many* shard swaps would thrash.
# Must stay well above one node's full shard span — a cold fingerprint cache
# after panel boot used to sum ~100 slots × N nodes and escalate every node
# into ``restart_node``, which OOMs 2GB Finalmask relays.
EXTREME_HOT_SWAP_THRESHOLD = 400
# Slot counts at/above this on a single plan look like cold-cache converge,
# not real churn — never escalate those to full restart.
COLD_CACHE_SLOT_FLOOR = 40
# One tick must not adi/rmi every dirty shard (100+ tags → DeadlineExceeded,
# then the 20s retry makes bulk-create Finalmask look "minutes late"). Newest
# slots (the accounts the customer just made) go first.
HOT_REPLACE_SLOT_BUDGET = 2
# A failed pass used to reschedule itself in 0.1s forever. Every retry dialed
# each node again, so an unreachable relay turned the loop into an RPyC hog and
# ``xray_users_transfer`` (Finalmask billing) started returning "node RPyC busy".
RETRY_BACKOFF_START_SEC = 1.0
RETRY_BACKOFF_MAX_SEC = 30.0
_retry_backoff_sec = RETRY_BACKOFF_START_SEC

_lock = threading.Lock()
_timer: Optional[threading.Timer] = None
_reload_in_flight = False
_pending_bulk = False
# Slots known dirty from outbox/user changes. When non-empty, hot path only
# considers these slots (plus fingerprint diffs) so 500k fleets do not rehash
# every shard on every debounce flush.
_dirty_slots: Set[int] = set()
# Insertion-ordered newest-last so take(limit) prefers the just-created shard.
_dirty_order: List[int] = []

# Per-node: structure fingerprint (restart required) and per-slot peer fingerprints.
_last_structure_fp: Dict[int, str] = {}
_last_shard_fps: Dict[int, Dict[int, str]] = {}

# Survive panel process restarts so the first schedule after boot diffs against
# the last successful apply instead of hot-replacing every shard blindly.
_FP_CACHE_PATH = "/var/lib/shahkar/cache/finalmask_fingerprints.json"


def _load_fp_cache() -> None:
    global _last_structure_fp, _last_shard_fps
    try:
        with open(_FP_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        _last_structure_fp = {
            int(k): str(v) for k, v in (data.get("structure") or {}).items()
        }
        _last_shard_fps = {
            int(nid): {int(s): str(fp) for s, fp in (slots or {}).items()}
            for nid, slots in (data.get("shards") or {}).items()
        }
        dirty = {int(s) for s in (data.get("dirty") or [])}
        if dirty:
            _dirty_slots |= dirty
            existing = set(_dirty_order)
            _dirty_order.extend(s for s in sorted(dirty) if s not in existing)
    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Finalmask fingerprint cache load failed", exc_info=True)


def _save_fp_cache() -> None:
    try:
        import os

        os.makedirs(os.path.dirname(_FP_CACHE_PATH), exist_ok=True)
        with _lock:
            dirty = sorted(int(s) for s in _dirty_slots)
            structure = {str(k): v for k, v in _last_structure_fp.items()}
            shards = {
                str(nid): {str(s): fp for s, fp in slots.items()}
                for nid, slots in _last_shard_fps.items()
            }
        payload = {
            "structure": structure,
            "shards": shards,
            # Survive panel restart: new WG users mark a slot dirty, then a
            # keep-live Xray core can miss the hot-replace. Boot reloads this
            # set and retries until the live inbound actually has the peer.
            "dirty": dirty,
        }
        tmp = _FP_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, _FP_CACHE_PATH)
    except Exception:
        logger.debug("Finalmask fingerprint cache save failed", exc_info=True)


_load_fp_cache()


def _active_peers_fingerprint(peers) -> str:
    """Fingerprint of peers that are actually baked into Finalmask inbounds."""
    parts = sorted(
        f"{p.user_id}:{p.public_key}:{p.address or p.awg_address or ''}:"
        f"{p.preshared_key or ''}:{int(getattr(p, 'finalmask_slot', 0) or 0)}"
        for p in peers
        if getattr(p, "active", False)
        and getattr(p, "public_key", None)
        and (getattr(p, "address", None) or getattr(p, "awg_address", None))
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _shard_fingerprints(peers) -> Dict[int, str]:
    """Per-slot fingerprint of active baked peers."""
    from app.wireguard.finalmask_shard import group_peers_by_slot

    shards = group_peers_by_slot(peers)
    out: Dict[int, str] = {}
    for slot, slot_peers in shards.items():
        out[int(slot)] = _active_peers_fingerprint(slot_peers)
    # Always include slot 0 so an empty first shard still has a stable key.
    out.setdefault(0, _active_peers_fingerprint([]))
    return out


def _structure_fingerprint(db, dbnode, node_id: int) -> str:
    """Fingerprint of Finalmask structure that cannot be hot-swapped alone."""
    from app.xray.operations import _finalmask_mtu_override, _finalmask_outbound_tag
    from app.wireguard.xray_native import DEFAULT_NOISE_SETTINGS

    cfg = dbnode.wireguard
    noise = cfg.xray_wg_noise or DEFAULT_NOISE_SETTINGS
    try:
        noise_s = json.dumps(noise, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        noise_s = str(noise)
    mtu = _finalmask_mtu_override(db, dbnode, node_id)
    if mtu is None:
        mtu = int(getattr(cfg, "xray_wg_mtu", None) or 1420)
    outbound = _finalmask_outbound_tag(db, dbnode, node_id)
    parts = [
        str(int(cfg.xray_wg_listen_port or 0)),
        str(cfg.private_key or ""),
        str(cfg.public_key or ""),
        noise_s,
        str(mtu),
        outbound or "DIRECT",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def mark_finalmask_slots_dirty(slots) -> None:
    """Record Finalmask shard slots that need a hot-replace on next flush."""
    global _dirty_slots
    try:
        cleaned = {int(s) for s in (slots or []) if s is not None}
    except (TypeError, ValueError):
        cleaned = set()
    if not cleaned:
        return
    with _lock:
        for slot in cleaned:
            _dirty_slots.add(slot)
            if slot in _dirty_order:
                _dirty_order.remove(slot)
            _dirty_order.append(slot)
    _save_fp_cache()


def take_finalmask_dirty_slots(limit: Optional[int] = None) -> Set[int]:
    """Pop dirty slots. ``limit`` keeps a large backlog from blocking new users."""
    global _dirty_slots
    with _lock:
        if not _dirty_slots:
            _dirty_order.clear()
            return set()
        if limit is None or int(limit) <= 0 or int(limit) >= len(_dirty_slots):
            out = set(_dirty_slots)
            _dirty_slots = set()
            _dirty_order.clear()
        else:
            out = set()
            while _dirty_order and len(out) < int(limit):
                slot = _dirty_order.pop()
                if slot in _dirty_slots:
                    _dirty_slots.discard(slot)
                    out.add(slot)
            _dirty_order[:] = [s for s in _dirty_order if s in _dirty_slots]
    if out:
        _save_fp_cache()
    return out


def peek_finalmask_dirty_slots() -> Set[int]:
    """Copy of slots waiting for a successful live hot-replace."""
    with _lock:
        return set(_dirty_slots)


def schedule_finalmask_xray_reload(
    *,
    delay: Optional[float] = None,
    bulk: bool = False,
) -> None:
    """Queue a debounced Finalmask reload on every node with Finalmask enabled."""
    from app.runtime_role import delegate_to_worker

    if delegate_to_worker("flush_finalmask"):
        return
    global _timer, _pending_bulk
    with _lock:
        if bulk:
            _pending_bulk = True
        if delay is None:
            delay = BULK_DEBOUNCE_SEC if _pending_bulk else DEFAULT_DEBOUNCE_SEC
        if _timer is not None:
            _timer.cancel()
        timer = threading.Timer(max(0.1, float(delay)), _run_finalmask_xray_reload)
        timer.daemon = True
        _timer = timer
        timer.start()
        logger.info("Scheduled Finalmask reload in %.1fs (bulk=%s)", delay, _pending_bulk)


def flush_finalmask_xray_reload(*, urgent: bool = False) -> bool:
    """Cancel debounce and run immediately (tests / explicit admin actions).

    ``urgent=True`` (disable/enable single user): skip slow per-node stats
    banking and apply dirty-slot hot-replaces in parallel so WireGuard cuts
    land near VLESS hot-remove latency.

    Returns True when every planned live adi/rmi succeeded (or nothing to do).
    """
    from app.runtime_role import delegate_to_worker

    if delegate_to_worker("flush_finalmask"):
        return True
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
    return bool(_run_finalmask_xray_reload(urgent=urgent))


def _finalmask_nodes(db) -> list:
    from app.db import crud
    from app.wireguard.xray_native import xray_native_wg_enabled

    return [
        n for n in crud.get_wireguard_nodes(db)
        if xray_native_wg_enabled(n.wireguard)
    ]


def hot_replace_finalmask_shards(
    node_id: int,
    changed_slots: Set[int],
    *,
    node_object=None,
    peers=None,
    skip_address_ensure: bool = False,
    skip_stats_flush: bool = False,
) -> bool:
    """Rebuild and hot-swap only the given Finalmask shard inbounds.

    Returns True on success. False means the caller should fall back to
    ``restart_node``. Does not touch routing (existing rules already list every
    shard tag → tunnel/WARP/DIRECT from the last full bake; new slots that did
    not exist yet fall back to restart so the routing rule is rewritten).

    ``skip_stats_flush=True`` for urgent disable/enable: skip the slow
    per-node transfer bank so the peer cut lands in ~one RTT. Usage still
    converges on the next record_usages tick.
    """
    from app import xray
    from app.db import GetDB, crud
    from app.wireguard.finalmask_shard import ensure_finalmask_slots, shard_inbound_tag
    from app.wireguard.operations import ensure_plain_addresses_for_finalmask
    from app.wireguard.peer_cache import peer_cache
    from app.wireguard.xray_native import build_xray_wireguard_shard_inbound
    from app.xray.operations import _finalmask_mtu_override

    if not changed_slots:
        return True

    # Shard rmi/adi drops unread per-user counters on that inbound. Bank them
    # into User.used_traffic first or Finalmask traffic never gets billed.
    # Urgent disable skips this — sequential multi-node flushes were the main
    # reason WG cut lagged seconds behind VLESS hot-remove.
    if not skip_stats_flush:
        try:
            from app.wireguard.finalmask_usage import flush_finalmask_node_stats

            flushed = flush_finalmask_node_stats(int(node_id))
            if flushed:
                logger.info(
                    "Finalmask node %s: flushed %s bytes of user stats before hot-replace",
                    node_id,
                    flushed,
                )
        except Exception:
            logger.debug(
                "Finalmask node %s: pre-hot-replace stats flush skipped",
                node_id,
                exc_info=True,
            )

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        cfg = dbnode.wireguard if dbnode else None
        if cfg is None:
            return False
        if not skip_address_ensure:
            ensure_plain_addresses_for_finalmask(db)
            ensure_finalmask_slots(db)
        if peers is None:
            peers = peer_cache.get_peers(db)
        mtu_override = _finalmask_mtu_override(db, dbnode, node_id)

        # Brand-new slots are not yet in the live routing rule. Try hot-add
        # first (rmi unknown-tag is fine); if the agent rejects or routing
        # would strand traffic, callers escalate via restart_node.
        known = set(_last_shard_fps.get(node_id, {}) or {})
        new_slots = sorted(
            s for s in changed_slots if s not in known and int(s) != 0
        )
        if known and new_slots:
            logger.info(
                "Finalmask node %s: hot-adding new shard slot(s) %s "
                "(not in fingerprint cache; may need restart if routing lacks tags)",
                node_id,
                new_slots,
            )

        from app.wireguard.finalmask_shard import group_peers_by_slot

        by_slot = group_peers_by_slot(peers)
        inbounds: List[dict] = []
        remove_tags: List[str] = []
        for slot in sorted(changed_slots):
            inbound = build_xray_wireguard_shard_inbound(
                cfg,
                by_slot.get(slot, []),
                node_id=node_id,
                slot=slot,
                mtu_override=mtu_override,
            )
            if inbound is None:
                return False
            tag = shard_inbound_tag(node_id, slot)
            remove_tags.append(tag)
            inbounds.append(inbound)

    if node_object is None:
        node_object = xray.nodes.get(node_id)
    if node_object is None:
        # One-shot callers (and a fresh panel process) have an empty
        # ``xray.nodes`` map — build a connection the same way restart_node does.
        try:
            from app.db import GetDB, crud as _crud

            with GetDB() as _db:
                _dbnode = _crud.get_node_by_id(_db, node_id)
            if _dbnode is None:
                return False
            node_object = xray.operations.add_node(_dbnode)
            xray.nodes[node_id] = node_object
        except Exception as exc:
            logger.warning("Finalmask hot replace: cannot attach node %s: %s", node_id, exc)
            return False
    if not getattr(node_object, "connected", False):
        try:
            node_object.connect()
        except Exception as exc:
            logger.warning("Finalmask hot replace: connect node %s failed: %s", node_id, exc)
            return False
    if not hasattr(node_object, "hot_replace_inbounds"):
        return False

    def _do_replace(target) -> tuple:
        try:
            result = target.hot_replace_inbounds(remove_tags, inbounds)
            return result, None
        except AttributeError as exc:
            return None, exc
        except Exception as exc:
            return None, exc

    result, err = _do_replace(node_object)
    if err is not None:
        msg = str(err).lower()
        if "no xray_hot_replace_inbounds_json" in msg or (
            isinstance(err, AttributeError) and "hot_replace" in msg
        ):
            _mark_agent_hot_unsupported(int(node_id))
        # Flaky direct RPyC mid-write — retry once over SSH control tunnel.
        # (Missing agent methods are not fixed by a tunnel; those need a rebuild.)
        stream_dead = (
            "stream has been closed" in msg
            or "connection reset" in msg
            or "result expired" in msg
        )
        if stream_dead:
            try:
                from app.db import GetDB, crud as _crud
                from app.xray.operations import _force_control_tunnel_session

                with GetDB() as _db:
                    _dbnode = _crud.get_node_by_id(_db, node_id)
                if _dbnode is not None:
                    forced = _force_control_tunnel_session(_dbnode, node_object)
                    if forced is not None:
                        xray.nodes[node_id] = forced
                        result, err = _do_replace(forced)
            except Exception as tunnel_exc:
                logger.warning(
                    "Finalmask hot replace tunnel retry node %s failed: %s",
                    node_id,
                    tunnel_exc,
                )

    if err is not None:
        logger.warning(
            "Finalmask hot replace on node %s failed: %s",
            node_id,
            err,
        )
        return False

    ok = bool(result.get("ok")) if isinstance(result, dict) else bool(result)
    if not ok:
        detail = ""
        if isinstance(result, dict):
            detail = str(result.get("detail") or "")
        detail_l = detail.lower()
        # rmi succeeded but adi hit a short CLI/API timeout — core is usually
        # still up. Retry in-place WITHOUT disconnect(): tearing the RPyC
        # session mid-fleet-sync is what flips nodes connecting↔connected.
        retryable_detail = (
            "deadlineexceeded" in detail_l
            or "context deadline exceeded" in detail_l
            or "existing tag found" in detail_l
            or "failed to dial" in detail_l
        )
        if retryable_detail:
            try:
                if not getattr(node_object, "connected", False):
                    node_object.connect()
                result2, err2 = _do_replace(node_object)
                if err2 is None and isinstance(result2, dict) and result2.get("ok"):
                    result = result2
                    ok = True
            except Exception as retry_exc:
                logger.warning(
                    "Finalmask hot replace retry node %s failed: %s",
                    node_id,
                    retry_exc,
                )
        elif "xray core is not running" in detail_l:
            # Leave reconnect to the health job / sync cooldown. Calling
            # connect_node here races the sync worker and flaps UI status.
            logger.warning(
                "Finalmask hot replace node %s: core down; holding for cooldown",
                node_id,
            )
        if not ok:
            logger.warning(
                "Finalmask hot replace on node %s returned not-ok: %s",
                node_id,
                result,
            )
            return False

    # Persist per-slot fingerprints as each shard lands so the cache grows
    # with the live peer set instead of staying stuck at a cold-boot snapshot.
    try:
        _agent_hot_ok[int(node_id)] = True
    except Exception:
        pass
    try:
        from app.wireguard.finalmask_shard import group_peers_by_slot as _gps

        slot_fps = _shard_fingerprints(peers)
        cur_map = dict(_last_shard_fps.get(node_id) or {})
        for slot in changed_slots:
            if int(slot) in slot_fps:
                cur_map[int(slot)] = slot_fps[int(slot)]
        _last_shard_fps[node_id] = cur_map
        _save_fp_cache()
    except Exception:
        logger.debug("Finalmask per-slot fingerprint update failed", exc_info=True)
    logger.info(
        "Finalmask hot replace ok on node %s slots=%s",
        node_id,
        sorted(int(s) for s in changed_slots),
    )
    return True


def _plan_node_reload(
    db, dbnode, peers, dirty_slots: Optional[Set[int]] = None,
) -> Tuple[str, Set[int], bool]:
    """Return ``(mode, changed_slots, structure_changed)``.

    ``mode`` is ``"noop"``, ``"hot"``, or ``"restart"``.
    When ``dirty_slots`` is provided, only those slots (plus fingerprint
    mismatches) are candidates for hot-replace — avoids O(all shards) work
    when the outbox already knows which slots moved.
    """
    node_id = dbnode.id
    structure = _structure_fingerprint(db, dbnode, node_id)
    shard_fps = _shard_fingerprints(peers)
    prev_structure = _last_structure_fp.get(node_id)
    prev_shards = _last_shard_fps.get(node_id) or {}

    # First sighting after a cold cache: remember structure so we do not
    # full-restart the core. Do **not** pretend every shard is already live —
    # that hid new peers after keep-live. Dirty slots (new users) hot-replace
    # immediately; a background walk covers the rest.
    if prev_structure is None:
        if dirty_slots:
            return "hot", {int(s) for s in dirty_slots}, False
        return "seed", set(), False

    structure_changed = prev_structure != structure
    changed: Set[int] = set()
    all_slots = set(shard_fps) | set(prev_shards)
    for slot in all_slots:
        if shard_fps.get(slot) != prev_shards.get(slot):
            changed.add(slot)
    if dirty_slots:
        changed |= {int(s) for s in dirty_slots}

    if structure_changed:
        return "restart", changed or {0}, True
    if not changed:
        return "noop", set(), False
    return "hot", changed, False


def _commit_fingerprints(node_id: int, db, dbnode, peers) -> None:
    """Persist fingerprints only after a successful apply."""
    _last_structure_fp[node_id] = _structure_fingerprint(db, dbnode, node_id)
    _last_shard_fps[node_id] = _shard_fingerprints(peers)
    _save_fp_cache()


def _commit_structure_only(node_id: int, db, dbnode) -> None:
    """Record listen/key/MTU fingerprint without claiming shards match live Xray."""
    _last_structure_fp[node_id] = _structure_fingerprint(db, dbnode, node_id)
    _save_fp_cache()


def _run_finalmask_xray_reload(*, urgent: bool = False) -> bool:
    global _timer, _reload_in_flight, _pending_bulk
    with _lock:
        _timer = None
        was_bulk = _pending_bulk
        _pending_bulk = False
        if _reload_in_flight:
            retry = 0.05 if urgent else (
                BULK_DEBOUNCE_SEC if was_bulk else DEFAULT_DEBOUNCE_SEC
            )
            timer = threading.Timer(
                retry,
                _run_finalmask_xray_reload,
                kwargs={"urgent": urgent},
            )
            timer.daemon = True
            _timer = timer
            timer.start()
            return False
        _reload_in_flight = True

    dirty: Set[int] = set()
    apply_failed: List[int] = []
    skipped_unreachable: List[Tuple[int, float]] = []
    try:
        from app.db import GetDB
        from app.wireguard.finalmask_shard import ensure_finalmask_slots
        from app.wireguard.operations import ensure_plain_addresses_for_finalmask
        from app.wireguard.peer_cache import peer_cache
        from app.xray.operations import restart_node

        dirty = take_finalmask_dirty_slots(limit=HOT_REPLACE_SLOT_BUDGET)
        plans: List[Tuple[int, str, Set[int]]] = []
        peers: List = []
        node_by_id: Dict[int, object] = {}
        with GetDB() as db:
            nodes = _finalmask_nodes(db)
            if not nodes:
                return True
            # Urgent disable/enable: skip fleet-wide address/slot scans — dirty
            # slots already identify what must change.
            if not urgent:
                ensure_plain_addresses_for_finalmask(db)
                ensure_finalmask_slots(db)
            peers = peer_cache.get_peers(db)
            for dbnode in nodes:
                node_by_id[int(dbnode.id)] = dbnode
                backoff_left = _node_backoff_left(dbnode.id)
                if backoff_left > 0:
                    skipped_unreachable.append((int(dbnode.id), round(backoff_left, 1)))
                    continue
                mode, changed, _ = _plan_node_reload(db, dbnode, peers, dirty_slots=dirty or None)
                if mode != "noop":
                    plans.append((dbnode.id, mode, changed))

        if skipped_unreachable:
            logger.info(
                "Finalmask reload: skipping unreachable node(s) %s — they resync "
                "from their own cursor on reconnect",
                skipped_unreachable,
            )

        unreachable_ids = {nid for nid, _left in skipped_unreachable}
        if not plans:
            reachable = [n for nid, n in node_by_id.items() if nid not in unreachable_ids]
            if dirty and reachable:
                # Fingerprint cache already matches DB (often a false "seed"
                # commit after keep-live). Still push the persisted dirty slots.
                for dbnode in reachable:
                    plans.append((int(dbnode.id), "hot", set(dirty)))
                logger.info(
                    "Finalmask reload: fingerprint cache clean but dirty slots %s — forcing live apply",
                    sorted(dirty),
                )
            else:
                if dirty:
                    # Every Finalmask node is in backoff; keep the slots so the
                    # peers land once one of them answers again.
                    mark_finalmask_slots_dirty(dirty)
                else:
                    logger.debug("Finalmask reload skipped: peer membership unchanged")
                return True

        # Extreme churn across many nodes: one restart each can be cheaper than
        # hundreds of sequential shard swaps — but never escalate a cold-cache
        # full-slot plan (panel boot) into restart (OOM on 2GB relays).
        total_changed = sum(len(c) for _, mode, c in plans if mode == "hot")
        if total_changed >= EXTREME_HOT_SWAP_THRESHOLD:
            escalated = []
            for nid, mode, slots in plans:
                if mode == "hot" and len(slots) >= COLD_CACHE_SLOT_FLOOR:
                    escalated.append((nid, "hot", slots))
                elif mode == "seed":
                    escalated.append((nid, mode, slots))
                else:
                    escalated.append((nid, "restart", slots))
            plans = escalated

        logger.info(
            "Finalmask reload on %s node(s): %s urgent=%s",
            len(plans),
            [(nid, mode, sorted(slots)[:12] + (["…"] if len(slots) > 12 else [])) for nid, mode, slots in plans],
            urgent,
        )

        # Reuse the peer list from planning — re-collecting 10k+ proxies per
        # node was pinning the panel at ~100% CPU for minutes after every boot.
        def _apply_plan(node_id: int, mode: str, changed: Set[int]) -> None:
            try:
                dbnode = node_by_id.get(int(node_id))
                if dbnode is None:
                    apply_failed.append(node_id)
                    return

                if mode == "seed" or (
                    mode == "hot" and len(changed) >= COLD_CACHE_SLOT_FLOOR
                ):
                    with GetDB() as db:
                        from app.db import crud

                        live = crud.get_node_by_id(db, node_id)
                        if live is None:
                            apply_failed.append(node_id)
                            return
                        _commit_structure_only(node_id, db, live)
                    apply_now = set(dirty or ()) or set()
                    if apply_now:
                        logger.info(
                            "Finalmask node %s: cold/seed — hot-replace dirty slots %s "
                            "(not claiming other shards live)",
                            node_id,
                            sorted(apply_now),
                        )
                        try:
                            from app.wireguard.sync_engine import mark_finalmask_rpc_busy

                            mark_finalmask_rpc_busy(node_id, True)
                            ok = hot_replace_finalmask_shards(
                                node_id,
                                apply_now,
                                peers=peers,
                                skip_address_ensure=True,
                                skip_stats_flush=urgent,
                            )
                        finally:
                            try:
                                from app.wireguard.sync_engine import mark_finalmask_rpc_busy

                                mark_finalmask_rpc_busy(node_id, False)
                            except Exception:
                                pass
                        if not ok:
                            apply_failed.append(node_id)
                            return
                    else:
                        logger.info(
                            "Finalmask node %s: seeded structure fingerprint "
                            "(%s planned shards, mode=%s)",
                            node_id,
                            len(changed),
                            mode,
                        )
                    return

                if mode == "hot":
                    if not _node_supports_hot_replace(int(node_id)):
                        if not _full_restart_allowed(int(node_id)):
                            logger.warning(
                                "Finalmask node %s: agent has no hot-replace; "
                                "skipping full restart (cooldown %.0fs left) — "
                                "peer diffs kept dirty until next allowed restart",
                                node_id,
                                _cooldown_left(int(node_id)),
                            )
                            # Do NOT commit fingerprints — apply on next allowed restart.
                            apply_failed.append(node_id)
                            return
                        logger.info(
                            "Finalmask node %s: agent has no hot-replace — full restart "
                            "(cooldown gate %ss)",
                            node_id,
                            int(FULL_RESTART_COOLDOWN_SEC),
                        )
                        if not urgent:
                            try:
                                from app.wireguard.finalmask_usage import (
                                    flush_finalmask_node_stats,
                                )

                                flush_finalmask_node_stats(int(node_id))
                            except Exception:
                                pass
                        _note_full_restart(int(node_id))
                        restart_node(node_id)
                        # restart_node is async + keep-live may skip the push.
                        # Never stamp fingerprints as applied here.
                        apply_failed.append(node_id)
                        return
                    try:
                        from app.wireguard.sync_engine import mark_finalmask_rpc_busy

                        mark_finalmask_rpc_busy(node_id, True)
                        ok = hot_replace_finalmask_shards(
                            node_id,
                            changed,
                            peers=peers,
                            skip_address_ensure=True,
                            skip_stats_flush=urgent,
                        )
                    finally:
                        try:
                            from app.wireguard.sync_engine import mark_finalmask_rpc_busy

                            mark_finalmask_rpc_busy(node_id, False)
                        except Exception:
                            pass
                    if not ok:
                        # Old agents lack ``xray_hot_replace_inbounds_json``.
                        # Retrying hot-replace forever leaves new peers offline.
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
                            _mark_agent_hot_unsupported(int(node_id))
                            if not _full_restart_allowed(int(node_id)):
                                logger.warning(
                                    "Finalmask hot replace unsupported on node %s; "
                                    "deferring full restart (cooldown %.0fs left)",
                                    node_id,
                                    _cooldown_left(int(node_id)),
                                )
                                apply_failed.append(node_id)
                                return
                            logger.warning(
                                "Finalmask hot replace unsupported on node %s; "
                                "falling back to full Xray restart (cooldown gate)",
                                node_id,
                            )
                            if not urgent:
                                try:
                                    from app.wireguard.finalmask_usage import (
                                        flush_finalmask_node_stats,
                                    )

                                    flush_finalmask_node_stats(int(node_id))
                                except Exception:
                                    pass
                            _note_full_restart(int(node_id))
                            restart_node(node_id)
                            apply_failed.append(node_id)
                            return
                        logger.warning(
                            "Finalmask hot replace failed on node %s; "
                            "deferring to resumable sync (no restart)",
                            node_id,
                        )
                        try:
                            from app.wireguard.sync_engine import on_node_connected

                            on_node_connected(int(node_id))
                        except Exception:
                            pass
                        apply_failed.append(node_id)
                        return
                else:
                    if not urgent:
                        try:
                            from app.wireguard.finalmask_usage import flush_finalmask_node_stats

                            flush_finalmask_node_stats(int(node_id))
                        except Exception:
                            logger.debug(
                                "Finalmask node %s: pre-restart stats flush skipped",
                                node_id,
                                exc_info=True,
                            )
                    restart_node(node_id)
                    apply_failed.append(node_id)
                    return

                with GetDB() as db:
                    from app.db import crud

                    live = crud.get_node_by_id(db, node_id)
                    if live is None:
                        apply_failed.append(node_id)
                        return
                    _commit_fingerprints(node_id, db, live, peers)
            except Exception:
                apply_failed.append(node_id)
                logger.exception("Finalmask reload failed on node %s", node_id)

        small_swap = bool(plans) and all(
            len(slots) <= HOT_REPLACE_SLOT_BUDGET for _nid, _mode, slots in plans
        )
        if (urgent or small_swap) and len(plans) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            workers = min(8, len(plans))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [
                    pool.submit(_apply_plan, int(nid), mode, changed)
                    for nid, mode, changed in plans
                ]
                for fut in as_completed(futs):
                    try:
                        fut.result()
                    except Exception:
                        logger.exception("Finalmask urgent parallel apply failed")
        else:
            for node_id, mode, changed in plans:
                _apply_plan(int(node_id), mode, changed)
    except Exception:
        logger.exception("Finalmask reload pass failed")
        mark_finalmask_slots_dirty(dirty)
        apply_failed.append(-1)
    finally:
        global _retry_backoff_sec
        if apply_failed:
            logger.warning(
                "Finalmask reload incomplete on nodes %s — keeping dirty slots %s",
                apply_failed,
                sorted(dirty),
            )
            mark_finalmask_slots_dirty(dirty)
            retry_in = _retry_backoff_sec
            _retry_backoff_sec = min(RETRY_BACKOFF_MAX_SEC, _retry_backoff_sec * 2)
        else:
            retry_in = 0.1
            _retry_backoff_sec = RETRY_BACKOFF_START_SEC
        with _lock:
            _reload_in_flight = False
            if _dirty_slots:
                timer = threading.Timer(retry_in, _run_finalmask_xray_reload)
                timer.daemon = True
                _timer = timer
                timer.start()
    return not bool(apply_failed)
