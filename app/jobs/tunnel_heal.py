"""Auto-heal Iran↔abroad tunnels without a manual Apply click.

When a relay/exit node flaps, ``connect_node`` used to keep a live Xray core
that no longer had ``tunnel-*-out`` / dokodemo capture — health looked fine
enough for TCP probes while traffic was dead until an admin hit Apply.

This job:
* re-applies enabled tunnels that fail health (with cooldown / failure streak)
* accepts ``schedule_reapply_for_node`` from hard-reconnect so tunnels come
  back as soon as the node is reachable again
"""
from __future__ import annotations

import threading
import time
from typing import Optional, Set

from app import feature_flags, logger, scheduler
from app.db import GetDB
from app.db.models import Tunnel
from config import (
    JOB_TUNNEL_HEAL_ENABLED,
    JOB_TUNNEL_HEAL_INTERVAL,
    TUNNEL_HEAL_COOLDOWN_SEC,
    TUNNEL_HEAL_FAILURE_THRESHOLD,
)

_lock = threading.Lock()
_pending_node_ids: Set[int] = set()
_pending_reason: dict[int, str] = {}
_fail_streak: dict[int, int] = {}
_last_apply_at: dict[int, float] = {}
_in_flight = False


def schedule_reapply_for_node(node_id: int, *, reason: str = "reconnect") -> None:
    """Queue every enabled tunnel that uses ``node_id`` for a re-apply."""
    node_id = int(node_id)
    with _lock:
        _pending_node_ids.add(node_id)
        _pending_reason[node_id] = reason


def _tunnels_for_node(db, node_id: int) -> list[Tunnel]:
    nid = int(node_id)
    return (
        db.query(Tunnel)
        .filter(
            Tunnel.enabled.is_(True),
            (Tunnel.relay_node_id == nid)
            | (Tunnel.exit_node_id == nid)
            | (Tunnel.intermediate_node_id == nid),
        )
        .order_by(Tunnel.id)
        .all()
    )


def _cooldown_ok(tunnel_id: int, now: float) -> bool:
    return (now - _last_apply_at.get(tunnel_id, 0.0)) >= float(TUNNEL_HEAL_COOLDOWN_SEC)


def _apply_one(db, tunnel: Tunnel, *, reason: str) -> bool:
    from app.routers.tunnel import _apply_tunnel

    tid = int(tunnel.id)
    try:
        result = _apply_tunnel(db, tunnel, health=True)
        healthy = bool((result.get("health") or {}).get("healthy"))
        _last_apply_at[tid] = time.monotonic()
        if healthy:
            _fail_streak.pop(tid, None)
            logger.info(
                "Tunnel %s (%s) auto-apply ok reason=%s",
                tid,
                tunnel.name,
                reason,
            )
            return True
        streak = _fail_streak.get(tid, 0) + 1
        _fail_streak[tid] = streak
        logger.warning(
            "Tunnel %s (%s) auto-apply finished but still unhealthy "
            "(%s/%s) reason=%s health=%s",
            tid,
            tunnel.name,
            streak,
            TUNNEL_HEAL_FAILURE_THRESHOLD,
            reason,
            result.get("health"),
        )
        return False
    except Exception as exc:
        _last_apply_at[tid] = time.monotonic()
        streak = _fail_streak.get(tid, 0) + 1
        _fail_streak[tid] = streak
        logger.warning(
            "Tunnel %s (%s) auto-apply failed (%s/%s) reason=%s: %s",
            tid,
            tunnel.name,
            streak,
            TUNNEL_HEAL_FAILURE_THRESHOLD,
            reason,
            exc,
        )
        return False


def tunnel_heal_tick() -> None:
    global _in_flight
    if not feature_flags.is_enabled("tunneling"):
        return
    with _lock:
        if _in_flight:
            return
        _in_flight = True
        pending = set(_pending_node_ids)
        reasons = dict(_pending_reason)
        _pending_node_ids.clear()
        _pending_reason.clear()

    try:
        from app.routers.tunnel import _tunnel_health

        now = time.monotonic()
        to_apply: dict[int, tuple[Tunnel, str]] = {}

        with GetDB() as db:
            for node_id in pending:
                reason = reasons.get(node_id, "reconnect")
                for tunnel in _tunnels_for_node(db, node_id):
                    if _cooldown_ok(int(tunnel.id), now):
                        to_apply[int(tunnel.id)] = (tunnel, f"{reason}:node-{node_id}")

            for tunnel in (
                db.query(Tunnel)
                .filter(Tunnel.enabled.is_(True))
                .order_by(Tunnel.id)
                .all()
            ):
                tid = int(tunnel.id)
                if tid in to_apply:
                    continue
                if not _cooldown_ok(tid, now):
                    continue
                try:
                    health = _tunnel_health(db, tunnel)
                except Exception as exc:
                    logger.debug("tunnel %s health probe failed: %s", tid, exc)
                    continue
                if health.get("healthy"):
                    _fail_streak.pop(tid, None)
                    continue
                streak = _fail_streak.get(tid, 0) + 1
                _fail_streak[tid] = streak
                if streak < int(TUNNEL_HEAL_FAILURE_THRESHOLD):
                    logger.info(
                        "Tunnel %s (%s) unhealthy (%s/%s) — waiting before auto-apply",
                        tid,
                        tunnel.name,
                        streak,
                        TUNNEL_HEAL_FAILURE_THRESHOLD,
                    )
                    continue
                to_apply[tid] = (tunnel, "health-fail")

            for tid, (tunnel, reason) in sorted(to_apply.items()):
                # Re-bind to this session (objects from earlier queries are fine
                # while the session is open).
                live = db.query(Tunnel).filter(Tunnel.id == tid).first()
                if live is None or not live.enabled:
                    continue
                _apply_one(db, live, reason=reason)
    finally:
        with _lock:
            _in_flight = False


from app.ha import run_if_leader  # noqa: E402

if JOB_TUNNEL_HEAL_ENABLED:
    scheduler.add_job(
        run_if_leader(tunnel_heal_tick),
        "interval",
        seconds=JOB_TUNNEL_HEAL_INTERVAL,
        coalesce=True,
        max_instances=1,
        id="tunnel_heal",
        replace_existing=True,
    )
