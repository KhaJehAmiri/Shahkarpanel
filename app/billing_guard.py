"""Fail-closed billing integrity when local Xray is untracked or stats cannot be collected.

When the panel serves *user-assignable* inbounds but usage accounting is blind,
users assigned to those local inbounds are disconnected after a grace period so
traffic cannot be consumed for free.

Important: this must **never** flip unrelated accounts to ``limited`` in the
database. ``limited`` blocks every product path (nodes, WireGuard, sing-box,
subscriptions). A transient local Xray API outage must only cut panel-local
sessions, not the whole fleet.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, List, Set

from config import (
    BILLING_BLIND_DISCONNECT_CYCLES,
    JOB_RECORD_USER_USAGES_INTERVAL,
    XRAY_EXECUTABLE_PATH,
)

if TYPE_CHECKING:
    from app import xray

logger = logging.getLogger(__name__)

_blind_local_cycles = 0
# When we fire a fail-closed disconnect, the core is deliberately restarted and
# its stats API is transiently unreachable while it comes back. Without a
# cooldown, the very next tick would see "billing blind" again, re-arm, and fire
# a second mass disconnect mid-restart — a self-feeding restart storm. Hold off
# re-arming for this long after a disconnect.
_last_disconnect_at = 0.0
_DISCONNECT_COOLDOWN_SEC = 60.0
_last_reclaim_at = 0.0
_RECLAIM_COOLDOWN_SEC = 10.0


def local_panel_has_inbounds(xray_module: "xray") -> bool:
    return bool((xray_module.config or {}).get("inbounds"))


def panel_has_user_billable_inbounds(xray_module: "xray") -> bool:
    """True when the panel exposes at least one user-assignable inbound."""
    from app.xray.inbound_ports import is_loopback_inbound, is_user_assignable_inbound

    for ib in (xray_module.config or {}).get("inbounds", []):
        if not isinstance(ib, dict):
            continue
        if not is_user_assignable_inbound(ib):
            continue
        if is_loopback_inbound(ib):
            continue
        return True
    return False


def assignable_panel_inbound_tags(xray_module: "xray") -> Set[str]:
    from app.xray.inbound_ports import is_user_assignable_inbound

    tags: Set[str] = set()
    for ib in (xray_module.config or {}).get("inbounds", []):
        if isinstance(ib, dict) and is_user_assignable_inbound(ib):
            tag = str(ib.get("tag") or "").strip()
            if tag:
                tags.add(tag)
    return tags


def local_xray_unmanaged(xray_module: "xray") -> bool:
    """True when stdin Xray PIDs exist outside the tracked core, or core should run but does not."""
    from app.xray.core import find_stdin_xray_pids

    pids = find_stdin_xray_pids(XRAY_EXECUTABLE_PATH)
    keep_pid = None
    if xray_module.core.process is not None:
        keep_pid = xray_module.core.process.pid

    if pids:
        if keep_pid is not None and keep_pid in pids and xray_module.core.started:
            return False
        return True

    return panel_has_user_billable_inbounds(xray_module) and not xray_module.core.started


def local_xray_api_reachable(xray_module: "xray") -> bool:
    try:
        xray_module.api.get_sys_stats(timeout=2)
        return True
    except Exception:
        return False


def _users_on_local_panel_xray(db, panel_tags: Set[str]) -> List:
    """Return active/on_hold users whose config includes a local panel inbound."""
    from app.db import crud
    from app.models.user import UserStatus

    if not panel_tags:
        return []

    users = crud.get_users(
        db,
        status=[UserStatus.active, UserStatus.on_hold],
        limit=10000,
    )
    out = []
    for user in users:
        assigned = {tag for tags in user.inbounds.values() for tag in tags}
        if assigned.intersection(panel_tags):
            out.append(user)
    return out


def _attempt_core_reclaim(xray_module: "xray") -> bool:
    """Best-effort reclaim of orphan stdin Xray before fail-closed disconnect."""
    global _last_reclaim_at

    now = time.time()
    if now - _last_reclaim_at < _RECLAIM_COOLDOWN_SEC:
        return False
    _last_reclaim_at = now

    try:
        xray_module.core._kill_stale_stdin_xray()
        if not xray_module.core.started:
            from app.xray import config as xray_config

            xray_module.core.restart(xray_config.include_db_users())
        api_ok = local_xray_api_reachable(xray_module)
        unmanaged = local_xray_unmanaged(xray_module)
        if api_ok and not unmanaged:
            logger.warning("billing_guard: reclaimed local Xray core after billing blind")
            return True
    except Exception:
        logger.exception("billing_guard: core reclaim failed")
    return False


def _disconnect_local_panel_users(xray_module: "xray") -> int:
    """Drop users served by local panel inbounds without mutating DB status."""
    from app.db import GetDB
    from app.quota import disconnect_users_everywhere, flush_live_serving

    panel_tags = assignable_panel_inbound_tags(xray_module)
    if not panel_tags:
        return 0

    with GetDB() as db:
        users = _users_on_local_panel_xray(db, panel_tags)

    if not users:
        return 0

    try:
        disconnect_users_everywhere(users)
    except Exception:
        logger.exception("billing_guard: hot disconnect for local panel users failed")

    logger.critical(
        "billing_guard: disconnected %d user(s) from local panel inbounds — "
        "local Xray billing was blind (DB status unchanged)",
        len(users),
    )
    try:
        flush_live_serving(force_restart=True)
    except Exception:
        logger.exception("billing_guard: core restart after local disconnect failed")
    return len(users)


def recover_false_billing_limits(db=None) -> int:
    """Reactivate ``limited`` users who still have quota headroom.

    Used after a billing_guard false positive where accounts were marked
    ``limited`` by older panel builds.
    """
    from datetime import datetime

    from app.db import GetDB
    from app.db.models import User
    from app.models.user import UserStatus
    from sqlalchemy import and_, or_

    def _run(session) -> int:
        now = datetime.utcnow()
        updated = (
            session.query(User)
            .filter(
                User.status == UserStatus.limited,
                or_(User.overage_traffic == 0, User.overage_traffic.is_(None)),
                or_(
                    User.data_limit.is_(None),
                    User.data_limit == 0,
                    and_(User.data_limit > 0, User.used_traffic < User.data_limit),
                ),
            )
            .update(
                {
                    User.status: UserStatus.active,
                    User.last_status_change: now,
                    User.edit_at: now,
                },
                synchronize_session=False,
            )
        )
        if updated:
            session.commit()
            logger.warning(
                "billing_guard: reactivated %d user(s) after false quota limit",
                updated,
            )
            try:
                from app.xray.operations import schedule_core_sync

                schedule_core_sync()
            except Exception:
                logger.debug("billing_guard: async core sync after recovery skipped", exc_info=True)
        return int(updated or 0)

    if db is not None:
        return _run(db)
    with GetDB() as session:
        return _run(session)


# Backwards-compatible name for tests/monkeypatches.
_disconnect_active_panel_users = _disconnect_local_panel_users


def check_billing_integrity(xray_module: "xray") -> None:
    """Increment blind-cycle counter and disconnect local users when billing stays blind."""
    global _blind_local_cycles, _last_disconnect_at

    if BILLING_BLIND_DISCONNECT_CYCLES <= 0:
        return

    if not panel_has_user_billable_inbounds(xray_module):
        _blind_local_cycles = 0
        return

    now = time.time()

    if getattr(xray_module.core, "restarting", False):
        _blind_local_cycles = max(0, _blind_local_cycles - 1)
        return

    if now - _last_disconnect_at < _DISCONNECT_COOLDOWN_SEC:
        _blind_local_cycles = 0
        return

    started_at = getattr(xray_module.core, "started_at", None)
    if started_at is not None and (now - started_at) < 15:
        _blind_local_cycles = max(0, _blind_local_cycles - 1)
        return

    unmanaged = local_xray_unmanaged(xray_module)
    api_ok = local_xray_api_reachable(xray_module)
    billing_ok = api_ok and (unmanaged or xray_module.core.started)

    if billing_ok:
        if _blind_local_cycles > 0:
            recover_false_billing_limits()
        _blind_local_cycles = max(0, _blind_local_cycles - 1)
        if unmanaged:
            logger.warning(
                "billing_guard: untracked local Xray PIDs but API stats OK — reclaim via health check"
            )
        return

    if _attempt_core_reclaim(xray_module):
        _blind_local_cycles = 0
        return

    _blind_local_cycles += 1
    grace_seconds = BILLING_BLIND_DISCONNECT_CYCLES * JOB_RECORD_USER_USAGES_INTERVAL
    logger.critical(
        "billing_guard: local billing BLIND (unmanaged=%s api_ok=%s core_started=%s) "
        "cycle %d/%d (~%ds until local disconnect)",
        unmanaged,
        api_ok,
        xray_module.core.started,
        _blind_local_cycles,
        BILLING_BLIND_DISCONNECT_CYCLES,
        max(0, grace_seconds - _blind_local_cycles * JOB_RECORD_USER_USAGES_INTERVAL),
    )

    if _blind_local_cycles >= BILLING_BLIND_DISCONNECT_CYCLES:
        _blind_local_cycles = 0
        _last_disconnect_at = time.time()
        _disconnect_local_panel_users(xray_module)


def reset_billing_guard_state() -> None:
    global _blind_local_cycles, _last_disconnect_at, _last_reclaim_at
    _blind_local_cycles = 0
    _last_disconnect_at = 0.0
    _last_reclaim_at = 0.0
