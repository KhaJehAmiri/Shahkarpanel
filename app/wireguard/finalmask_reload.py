"""Debounced Xray reload for Finalmask (Xray-native WG) peer membership.

Kernel WireGuard peers update via ``wg syncconf`` on every user change, but
Finalmask peers are baked into the node's Xray config. Without a restart
(or equivalent config push), newly enabled users cannot dial Finalmask and
disabled users may keep working until something else restarts Xray.

Call ``schedule_finalmask_xray_reload`` after peer membership changes. Rapid
bursts (bulk enable, mass disable) coalesce into one restart per node.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger("nexus-wg")

# Long enough to coalesce bulk ops / rapid edits; short enough that a new
# subscriber gets Finalmask within a few seconds of enable.
DEFAULT_DEBOUNCE_SEC = 5.0

_lock = threading.Lock()
_timer: Optional[threading.Timer] = None
_reload_in_flight = False


def schedule_finalmask_xray_reload(*, delay: float = DEFAULT_DEBOUNCE_SEC) -> None:
    """Queue a debounced Xray restart on every node with Finalmask enabled."""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
        timer = threading.Timer(max(0.1, float(delay)), _run_finalmask_xray_reload)
        timer.daemon = True
        _timer = timer
        timer.start()
        logger.debug("Scheduled Finalmask Xray reload in %.1fs", delay)


def flush_finalmask_xray_reload() -> None:
    """Cancel debounce and run immediately (tests / explicit admin actions)."""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
    _run_finalmask_xray_reload()


def _finalmask_node_ids(db) -> list[int]:
    from app.db import crud
    from app.wireguard.xray_native import xray_native_wg_enabled

    out: list[int] = []
    for node in crud.get_wireguard_nodes(db):
        if xray_native_wg_enabled(node.wireguard):
            out.append(node.id)
    return out


def _run_finalmask_xray_reload() -> None:
    global _timer, _reload_in_flight
    with _lock:
        _timer = None
        if _reload_in_flight:
            # Another reload is mid-flight; schedule a follow-up so we don't
            # drop a peer change that landed while restarting.
            timer = threading.Timer(DEFAULT_DEBOUNCE_SEC, _run_finalmask_xray_reload)
            timer.daemon = True
            _timer = timer
            timer.start()
            return
        _reload_in_flight = True

    try:
        from app.db import GetDB
        from app.xray.operations import restart_node

        with GetDB() as db:
            node_ids = _finalmask_node_ids(db)
        if not node_ids:
            return

        logger.info(
            "Reloading Finalmask Xray inbound on %s node(s): %s",
            len(node_ids),
            node_ids,
        )
        for node_id in node_ids:
            try:
                restart_node(node_id)
            except Exception:
                logger.exception(
                    "Finalmask Xray reload failed on node %s",
                    node_id,
                )
    except Exception:
        logger.exception("Finalmask Xray reload pass failed")
    finally:
        with _lock:
            _reload_in_flight = False
