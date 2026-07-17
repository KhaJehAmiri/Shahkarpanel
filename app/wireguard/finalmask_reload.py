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
from typing import Dict, List, Optional, Set, Tuple

# Use uvicorn's error logger so Finalmask reload lines show in panel docker logs
# (the dedicated nexus-wg logger is often unconfigured and silent).
logger = logging.getLogger("uvicorn.error")

DEFAULT_DEBOUNCE_SEC = 5.0
BULK_DEBOUNCE_SEC = 15.0
# Heuristic: if this many shard fingerprints differ at once, prefer the longer
# coalesce window so a bulk enable lands as one hot-replace per touched shard.
BULK_DIFF_THRESHOLD = 3
# Only fall back to a full-core restart when *many* shard swaps would thrash;
# must stay above a single node's full shard count (first converge after panel
# start hot-replaces every slot) so that path never becomes a tunnel-dropping
# restart.
EXTREME_HOT_SWAP_THRESHOLD = 80

_lock = threading.Lock()
_timer: Optional[threading.Timer] = None
_reload_in_flight = False
_pending_bulk = False

# Per-node: structure fingerprint (restart required) and per-slot peer fingerprints.
_last_structure_fp: Dict[int, str] = {}
_last_shard_fps: Dict[int, Dict[int, str]] = {}

# Survive panel process restarts so the first schedule after boot diffs against
# the last successful apply instead of hot-replacing every shard blindly.
_FP_CACHE_PATH = "/var/lib/nexuspanel/cache/finalmask_fingerprints.json"


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
    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Finalmask fingerprint cache load failed", exc_info=True)


def _save_fp_cache() -> None:
    try:
        import os

        os.makedirs(os.path.dirname(_FP_CACHE_PATH), exist_ok=True)
        payload = {
            "structure": {str(k): v for k, v in _last_structure_fp.items()},
            "shards": {
                str(nid): {str(s): fp for s, fp in slots.items()}
                for nid, slots in _last_shard_fps.items()
            },
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


def schedule_finalmask_xray_reload(
    *,
    delay: Optional[float] = None,
    bulk: bool = False,
) -> None:
    """Queue a debounced Finalmask reload on every node with Finalmask enabled."""
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


def flush_finalmask_xray_reload() -> None:
    """Cancel debounce and run immediately (tests / explicit admin actions)."""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
    _run_finalmask_xray_reload()


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
) -> bool:
    """Rebuild and hot-swap only the given Finalmask shard inbounds.

    Returns True on success. False means the caller should fall back to
    ``restart_node``. Does not touch routing (existing rules already list every
    shard tag → tunnel/WARP/DIRECT from the last full bake; new slots that did
    not exist yet fall back to restart so the routing rule is rewritten).
    """
    from app import xray
    from app.db import GetDB, crud
    from app.wireguard.finalmask_shard import ensure_finalmask_slots, shard_inbound_tag
    from app.wireguard.operations import collect_wg_peers, ensure_plain_addresses_for_finalmask
    from app.wireguard.xray_native import build_xray_wireguard_shard_inbound
    from app.xray.operations import _finalmask_mtu_override

    if not changed_slots:
        return True

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        cfg = dbnode.wireguard if dbnode else None
        if cfg is None:
            return False
        ensure_plain_addresses_for_finalmask(db)
        ensure_finalmask_slots(db)
        peers = collect_wg_peers(db)
        mtu_override = _finalmask_mtu_override(db, dbnode, node_id)

        # A brand-new slot has no routing rule entry yet → need full restart.
        known = set(_last_shard_fps.get(node_id, {}) or {})
        if any(slot not in known and slot != 0 for slot in changed_slots):
            # First-ever apply (known empty) still allows hot add of slot 0 only
            # when the core was baked with that tag already; safer to restart
            # when introducing any never-seen slot.
            if known and any(slot not in known for slot in changed_slots):
                logger.info(
                    "Finalmask node %s: new shard slot(s) %s require full restart",
                    node_id,
                    sorted(s for s in changed_slots if s not in known),
                )
                return False

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

    try:
        result = node_object.hot_replace_inbounds(remove_tags, inbounds)
    except AttributeError:
        return False
    except Exception as exc:
        logger.warning(
            "Finalmask hot replace on node %s failed: %s",
            node_id,
            exc,
        )
        return False

    ok = bool(result.get("ok")) if isinstance(result, dict) else bool(result)
    if not ok:
        logger.warning(
            "Finalmask hot replace on node %s returned not-ok: %s",
            node_id,
            result,
        )
    return ok


def _plan_node_reload(
    db, dbnode, peers,
) -> Tuple[str, Set[int], bool]:
    """Return ``(mode, changed_slots, structure_changed)``.

    ``mode`` is ``"noop"``, ``"hot"``, or ``"restart"``.
    """
    node_id = dbnode.id
    structure = _structure_fingerprint(db, dbnode, node_id)
    shard_fps = _shard_fingerprints(peers)
    prev_structure = _last_structure_fp.get(node_id)
    prev_shards = _last_shard_fps.get(node_id) or {}

    # First sighting after panel start: hot-replace every shard once so DB and
    # the live core converge without a full restart (tunnel stays up). Skipping
    # apply here would let a membership change that *triggered* the first
    # schedule get fingerprinted but never pushed.
    if prev_structure is None:
        return "hot", set(shard_fps.keys()) or {0}, False

    structure_changed = prev_structure != structure
    changed: Set[int] = set()
    all_slots = set(shard_fps) | set(prev_shards)
    for slot in all_slots:
        if shard_fps.get(slot) != prev_shards.get(slot):
            changed.add(slot)

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


def _run_finalmask_xray_reload() -> None:
    global _timer, _reload_in_flight, _pending_bulk
    with _lock:
        _timer = None
        was_bulk = _pending_bulk
        _pending_bulk = False
        if _reload_in_flight:
            timer = threading.Timer(
                BULK_DEBOUNCE_SEC if was_bulk else DEFAULT_DEBOUNCE_SEC,
                _run_finalmask_xray_reload,
            )
            timer.daemon = True
            _timer = timer
            timer.start()
            return
        _reload_in_flight = True

    try:
        from app.db import GetDB
        from app.wireguard.finalmask_shard import ensure_finalmask_slots
        from app.wireguard.operations import (
            collect_wg_peers,
            ensure_plain_addresses_for_finalmask,
        )
        from app.xray.operations import restart_node

        plans: List[Tuple[int, str, Set[int]]] = []
        with GetDB() as db:
            nodes = _finalmask_nodes(db)
            if not nodes:
                return
            ensure_plain_addresses_for_finalmask(db)
            ensure_finalmask_slots(db)
            peers = collect_wg_peers(db)
            for dbnode in nodes:
                mode, changed, _ = _plan_node_reload(db, dbnode, peers)
                if mode != "noop":
                    plans.append((dbnode.id, mode, changed))

        if not plans:
            logger.debug("Finalmask reload skipped: peer membership unchanged")
            return

        # Extreme churn across many nodes: one restart each is cheaper than
        # hundreds of sequential shard swaps. A single node's full converge
        # (≤ FINALMASK_SHARD_PORT_RESERVE slots) must stay on the hot path.
        total_changed = sum(len(c) for _, mode, c in plans if mode == "hot")
        if total_changed >= EXTREME_HOT_SWAP_THRESHOLD:
            plans = [(nid, "restart", slots) for nid, _, slots in plans]

        logger.info(
            "Finalmask reload on %s node(s): %s",
            len(plans),
            [(nid, mode, sorted(slots)) for nid, mode, slots in plans],
        )

        for node_id, mode, changed in plans:
            try:
                if mode == "hot":
                    ok = hot_replace_finalmask_shards(node_id, changed)
                    if not ok:
                        logger.warning(
                            "Finalmask hot replace failed on node %s; falling back to restart",
                            node_id,
                        )
                        restart_node(node_id)
                else:
                    restart_node(node_id)

                with GetDB() as db:
                    from app.db import crud

                    dbnode = crud.get_node_by_id(db, node_id)
                    if dbnode is None:
                        continue
                    ensure_plain_addresses_for_finalmask(db)
                    ensure_finalmask_slots(db)
                    peers = collect_wg_peers(db)
                    _commit_fingerprints(node_id, db, dbnode, peers)
            except Exception:
                logger.exception("Finalmask reload failed on node %s", node_id)
    except Exception:
        logger.exception("Finalmask reload pass failed")
    finally:
        with _lock:
            _reload_in_flight = False
