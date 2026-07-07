"""Fail-closed billing integrity when local Xray is untracked or stats cannot be collected.

When the panel serves inbounds but usage accounting is blind, active users are
disconnected after a short grace period so traffic cannot be consumed for free.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

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


def local_panel_has_inbounds(xray_module: "xray") -> bool:
    return bool((xray_module.config or {}).get("inbounds"))


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

    return local_panel_has_inbounds(xray_module) and not xray_module.core.started


def local_xray_api_reachable(xray_module: "xray") -> bool:
    try:
        xray_module.api.get_sys_stats(timeout=2)
        return True
    except Exception:
        return False


def _disconnect_active_panel_users() -> int:
    """Mark active users limited in DB, then flush cores once (not per-user re-sync)."""
    from app.db import GetDB, crud
    from app.models.user import UserStatus
    from app.quota import flush_live_serving

    count = 0
    with GetDB() as db:
        users = crud.get_users(
            db,
            status=[UserStatus.active, UserStatus.on_hold],
            limit=10000,
        )
        for user in users:
            try:
                crud.update_user_status(db, user, UserStatus.limited)
                count += 1
            except Exception:
                logger.exception("billing_guard: failed to limit user %s", user.username)
        db.commit()

    if count:
        logger.critical(
            "billing_guard: limited %d active user(s) — local Xray billing was blind",
            count,
        )
        # ``flush_live_serving(force_restart=True)`` already rebuilds the config
        # (limited users excluded) and force-restarts the core once. A second
        # explicit ``xray.core.restart`` here was a redundant back-to-back
        # restart — one is enough for the fail-closed reset.
        try:
            flush_live_serving(force_restart=True)
        except Exception:
            logger.exception("billing_guard: core restart after mass disconnect failed")
    return count


def check_billing_integrity(xray_module: "xray") -> None:
    """Increment blind-cycle counter and disconnect users when billing stays blind."""
    global _blind_local_cycles, _last_disconnect_at

    if BILLING_BLIND_DISCONNECT_CYCLES <= 0:
        return

    if not local_panel_has_inbounds(xray_module):
        _blind_local_cycles = 0
        return

    now = time.time()

    # A restart in progress makes the stats API expectedly unreachable. Counting
    # that as "billing blind" is what let billing_guard fire a disconnect whose
    # own restart kept the API down, which tripped billing_guard again — a
    # self-feeding restart storm. Skip and unwind the counter instead.
    if getattr(xray_module.core, "restarting", False):
        _blind_local_cycles = max(0, _blind_local_cycles - 1)
        return

    # After we just fired a fail-closed disconnect the core is restarting and
    # settling; stay quiet until it has had time to come back before re-arming.
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
        _blind_local_cycles = max(0, _blind_local_cycles - 1)
        if unmanaged:
            logger.warning(
                "billing_guard: untracked local Xray PIDs but API stats OK — reclaim via health check"
            )
        return

    _blind_local_cycles += 1
    grace_seconds = BILLING_BLIND_DISCONNECT_CYCLES * JOB_RECORD_USER_USAGES_INTERVAL
    logger.critical(
        "billing_guard: local billing BLIND (unmanaged=%s api_ok=%s core_started=%s) "
        "cycle %d/%d (~%ds until disconnect)",
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
        _disconnect_active_panel_users()


def reset_billing_guard_state() -> None:
    global _blind_local_cycles, _last_disconnect_at
    _blind_local_cycles = 0
    _last_disconnect_at = 0.0
