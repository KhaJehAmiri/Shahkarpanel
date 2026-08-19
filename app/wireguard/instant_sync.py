"""Immediate WireGuard peer provision + Finalmask push for a single user.

User create used to only write ``Proxy(WireGuard)`` keys, then wait on a
multi-second debounce chain before ``WgPeer`` / address / Finalmask existed.
This module allocates identity and flushes Finalmask right away so subscription
links and node peers land in one shot.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger("uvicorn.error")

_lock = threading.Lock()
_inflight: set[int] = set()


def provision_and_sync_wireguard_user(
    user_id: int,
    *,
    immediate: bool = True,
    push: bool = True,
) -> bool:
    """Allocate WG address/slot for ``user_id`` and optionally push Finalmask.

    ``push=False`` is for the API process: persist IP/slot/dirty file, then
    the outbox worker applies to nodes.
    """
    uid = int(user_id)
    with _lock:
        if uid in _inflight:
            return False
        _inflight.add(uid)

    try:
        return _provision_and_sync(uid, immediate=immediate, push=push)
    finally:
        with _lock:
            _inflight.discard(uid)


def _provision_and_sync(user_id: int, *, immediate: bool, push: bool = True) -> bool:
    from app.db import GetDB, crud
    from app.models.proxy import ProxyTypes
    from app.models.user import UserStatus
    from app.wireguard.finalmask_reload import (
        mark_finalmask_slots_dirty,
        schedule_finalmask_xray_reload,
    )
    from app.wireguard.finalmask_shard import ensure_finalmask_slots, user_finalmask_slot
    from app.wireguard.wg_manager import autoscale_enabled, create_peer

    slot: Optional[int] = None
    with GetDB() as db:
        dbuser = crud.get_user_by_id(db, user_id)
        if dbuser is None:
            return False

        from app.db.proxy_dedupe import get_user_proxy

        proxy = get_user_proxy(db, user_id, ProxyTypes.WireGuard)
        if proxy is None:
            return False

        try:
            if autoscale_enabled():
                create_peer(db, user_id, sync=False)
            else:
                from app.wireguard.operations import ensure_plain_addresses_for_finalmask

                ensure_plain_addresses_for_finalmask(db)
        except Exception:
            logger.exception(
                "WireGuard instant provision failed for user %s", user_id,
            )
            return False

        # Wake resumable sync so tunnel-exit kernel WG (and other nodes) pick
        # up the new peer without waiting for the next churn event.
        if push:
            try:
                from app.wireguard.operations import sync_user_change

                sync_user_change()
            except Exception:
                logger.debug(
                    "sync_user_change after instant WG provision failed for user %s",
                    user_id,
                    exc_info=True,
                )

        try:
            ensure_finalmask_slots(db)
        except Exception:
            logger.exception(
                "Finalmask slot assign failed for user %s", user_id,
            )

        db.refresh(proxy)
        slot = user_finalmask_slot(dict(proxy.settings or {}))

        served = dbuser.status in (UserStatus.active,)
        if not served:
            logger.info(
                "WireGuard user %s provisioned (slot=%s) — skip Finalmask push (status=%s)",
                user_id,
                slot,
                dbuser.status,
            )
            return True

    if slot is not None:
        mark_finalmask_slots_dirty([slot])

    if push:
        schedule_finalmask_xray_reload(delay=0.1, bulk=False)
        if immediate:
            threading.Thread(
                target=_flush_finalmask_safe,
                name=f"wg-flush-{user_id}",
                daemon=True,
            ).start()
    logger.info(
        "WireGuard user %s synced to Finalmask (slot=%s immediate=%s push=%s)",
        user_id,
        slot,
        immediate,
        push,
    )
    return True


def _flush_finalmask_safe() -> None:
    try:
        from app.wireguard.finalmask_reload import flush_finalmask_xray_reload

        flush_finalmask_xray_reload()
    except Exception:
        logger.exception("Finalmask background flush failed")


def schedule_provision_and_sync_wireguard_user(user_id: int) -> None:
    """Fire-and-forget wrapper for API background tasks."""
    def _run():
        try:
            provision_and_sync_wireguard_user(user_id, immediate=True)
        except Exception:
            logger.exception(
                "Background WireGuard instant sync failed for user %s", user_id,
            )

    threading.Thread(
        target=_run,
        name=f"wg-instant-{user_id}",
        daemon=True,
    ).start()
