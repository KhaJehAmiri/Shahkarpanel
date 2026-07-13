"""Data-limit enforcement helpers (shared by usage recording and review job)."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import Admin, User
from app.models.user import UserStatus

logger = logging.getLogger("nexus-quota")

_force_disconnect_after: dict[int, float] = {}
_FORCE_DISCONNECT_COOLDOWN_SEC = 15.0

# Global cooldown so a briefly-unreachable core API cannot restart-loop every
# review/usage tick (which freezes stats collection and Overview KPIs).
_last_disconnect_restart_at: float = 0.0
_DISCONNECT_RESTART_COOLDOWN_SEC = 90.0

# Consecutive usage ticks each non-billable user has kept leaking traffic after
# the live handler-API remove. Only a sustained streak escalates to a restart.
_leak_streak: dict[int, int] = {}

# A user who is already ``limited`` is excluded from the generated core config,
# so re-asserting their disconnect on every review tick is pointless churn.
# Disconnect is now a live handler-API remove (no restart), but re-issuing it
# for the same user every few seconds is still wasteful, so keep it as an
# occasional safety net: re-assert at most once per this window per user.
_limited_redisconnect_after: dict[int, float] = {}
_LIMITED_REDISCONNECT_COOLDOWN_SEC = 300.0


def quota_exhausted(dbuser: User) -> bool:
    """True when a finite data limit exists and usage has reached it."""
    if not dbuser.data_limit or dbuser.data_limit <= 0:
        return False
    return int(dbuser.used_traffic) >= int(dbuser.data_limit)


def reactivate_if_quota_available(dbuser: User) -> bool:
    """Move ``limited`` → ``active`` when quota headroom exists (e.g. after recharge)."""
    if dbuser.status != UserStatus.limited or quota_exhausted(dbuser):
        return False
    if int(getattr(dbuser, "overage_traffic", 0) or 0) > 0:
        return False
    dbuser.status = UserStatus.active
    dbuser.last_status_change = datetime.utcnow()
    return True


def apply_overage_on_recharge(dbuser: User, new_data_limit: Optional[int]) -> None:
    """Apply accumulated post-limit bytes against a recharged package.

    ``used_traffic`` already holds billable bytes up to the old limit; ``overage_traffic``
    holds everything consumed while limited/expired. On recharge both must count toward
    the new package — not overage alone.
    """
    overage = int(getattr(dbuser, "overage_traffic", 0) or 0)
    if overage <= 0:
        return
    if not new_data_limit or new_data_limit <= 0:
        dbuser.used_traffic = int(dbuser.used_traffic or 0) + overage
        dbuser.overage_traffic = 0
        logger.info(
            'User "%s" unlimited recharge absorbed %s bytes overage into used=%s',
            dbuser.username,
            overage,
            dbuser.used_traffic,
        )
        return
    limit = int(new_data_limit)
    total_consumed = int(dbuser.used_traffic or 0) + overage
    dbuser.used_traffic = min(total_consumed, limit)
    dbuser.overage_traffic = max(0, total_consumed - limit)
    logger.info(
        'User "%s" recharge applied total=%s (used+overage) against limit=%s → used=%s overage=%s',
        dbuser.username,
        total_consumed,
        limit,
        dbuser.used_traffic,
        dbuser.overage_traffic,
    )


def remaining_traffic(dbuser: User) -> Optional[int]:
    """Billable bytes left in the current package (None = unlimited)."""
    if not dbuser.data_limit or dbuser.data_limit <= 0:
        return None
    return max(0, int(dbuser.data_limit) - int(dbuser.used_traffic or 0))


def clamp_usage_delta(used: int, limit: Optional[int], delta: int) -> int:
    """Return billable bytes without exceeding ``limit`` (strict, no overage)."""
    if not limit or limit <= 0 or delta <= 0:
        return max(0, int(delta))
    remaining = max(0, int(limit) - int(used))
    return min(int(delta), remaining)


def enforce_usage_cap(db: Session, dbuser: User) -> bool:
    """Clamp ``used_traffic`` to ``data_limit`` (strict, no overage)."""
    if not dbuser.data_limit or dbuser.data_limit <= 0:
        return False
    capped = min(int(dbuser.used_traffic), int(dbuser.data_limit))
    if capped == int(dbuser.used_traffic):
        return False
    dbuser.used_traffic = capped
    db.commit()
    return True


def limit_user_quota(db: Session, dbuser: User, *, cap_usage: bool = True, disconnect: bool = True) -> bool:
    """Move an active user to ``limited`` and stop serving traffic.

    The user row, proxy keys, and WG address are preserved for recharge.
    Only the live peer/inbound is removed until quota is restored.

    ``disconnect=False`` performs the DB status change only and skips the live
    disconnect, so a caller processing many users in one tick can collect them
    and issue a single batched ``disconnect_users_everywhere`` instead of one
    disconnect pass per user (see ``record_usages``).
    """
    if cap_usage:
        enforce_usage_cap(db, dbuser)

    if dbuser.status != UserStatus.active:
        return False
    if not dbuser.data_limit or dbuser.used_traffic < dbuser.data_limit:
        return False

    crud.update_user_status(db, dbuser, UserStatus.limited)
    if disconnect:
        disconnect_user_everywhere(dbuser)
    logger.info('User "%s" limited at %s/%s bytes', dbuser.username, dbuser.used_traffic, dbuser.data_limit)
    return True


def resellers_over_traffic_cap(db: Session) -> Tuple[set, set]:
    """Split non-sudo admins with a total-traffic cap into (over, under) sets.

    A reseller is "over" once the running ``users_usage`` total reaches their
    ``max_total_traffic``. Admins with no cap (NULL) are ignored entirely.
    """
    over: set = set()
    under: set = set()
    rows = (
        db.query(Admin.id, Admin.users_usage, Admin.max_total_traffic)
        .filter(Admin.is_sudo.is_(False), Admin.max_total_traffic.isnot(None))
        .all()
    )
    for admin_id, usage, cap in rows:
        if int(usage or 0) >= int(cap):
            over.add(admin_id)
        else:
            under.add(admin_id)
    return over, under


def enforce_reseller_traffic_caps(db: Session):
    """Suspend/restore users based on their reseller's total-traffic cap.

    - Over-cap resellers: every currently ``active`` user is disabled and flagged
      ``capped_by_reseller`` so it can be brought back later.
    - Under-cap resellers: users this flag marks are reactivated (to ``active``,
      or ``limited`` if their own quota is exhausted), never touching users the
      admin disabled manually.

    Returns ``(newly_suspended, reactivated_ids)`` so the caller can run the live
    disconnect / core re-sync **after** the DB session closes (mirrors review()).
    """
    from types import SimpleNamespace

    over_ids, under_ids = resellers_over_traffic_cap(db)
    newly: List[SimpleNamespace] = []
    reactivated: List[int] = []

    if over_ids:
        for u in (
            db.query(User)
            .filter(User.admin_id.in_(over_ids), User.status == UserStatus.active)
            .all()
        ):
            u.status = UserStatus.disabled
            u.capped_by_reseller = True
            u.last_status_change = datetime.utcnow()
            newly.append(SimpleNamespace(id=int(u.id), username=u.username))

    if under_ids:
        for u in (
            db.query(User)
            .filter(
                User.admin_id.in_(under_ids),
                User.capped_by_reseller.is_(True),
            )
            .all()
        ):
            u.capped_by_reseller = False
            u.last_status_change = datetime.utcnow()
            if quota_exhausted(u):
                # Their own package is spent — don't serve, let review() manage it.
                u.status = UserStatus.limited
            else:
                u.status = UserStatus.active
                reactivated.append(int(u.id))

    if newly or reactivated:
        db.commit()
    return newly, reactivated


def flush_live_serving(*, force_restart: bool = False) -> None:
    """Push current DB user statuses to every live core/node once."""
    from app.xray.serving import sync_core_users_now

    sync_core_users_now(force_restart=force_restart)

    try:
        from app.xray.operations import push_connected_nodes_config_sync

        push_connected_nodes_config_sync()
    except Exception:
        logger.exception("Node Xray config push during live serving flush failed")


def disconnect_users_everywhere(
    dbusers: Sequence[User],
    *,
    allow_restart: bool = True,
) -> bool:
    """Drop a *set* of users from every live path **without disconnecting anyone else**.

    Removes the users through the Xray handler gRPC API (add/remove-user) on the
    main core and every connected node — the same live-mutation path 3x-ui uses
    — so unrelated users keep their sessions. A full-core restart is issued only
    as a fallback when the main core's API is unreachable (the sole way to
    converge a dead core), and even then just **once** for the whole batch
    (and never more often than ``_DISCONNECT_RESTART_COOLDOWN_SEC``).

    Pass ``allow_restart=False`` for safety-net re-asserts on users who are
    already absent from generated config (e.g. ``limited``) — a restart is not
    required and would thrash the core when the API is briefly down.

    This blocks the users' *new* connections instantly. A stubborn, already
    established session that keeps transferring after removal (e.g. a long-lived
    SS-2022 or bulk TCP stream that bypasses the quota) is caught and force-cut
    by the traffic-verified ``enforce_disconnect_for_non_billable`` escalation —
    something 3x-ui never does. Returns True when at least one user was handled.
    """
    global _last_disconnect_restart_at

    users = list(dbusers)
    if not users:
        return False

    hot_ok = False
    try:
        from app.xray.serving import hot_disconnect_users

        hot_ok = hot_disconnect_users(users)
    except Exception:
        logger.exception("Main-core hot disconnect failed; falling back to restart")

    if hot_ok:
        try:
            from app.xray.operations import hot_disconnect_users_on_nodes

            hot_disconnect_users_on_nodes(users)
        except Exception:
            logger.debug("Node hot disconnect skipped", exc_info=True)
    elif allow_restart:
        from app import xray

        now = time.monotonic()
        if getattr(xray.core, "restarting", False):
            logger.warning(
                "Skipping disconnect restart fallback — core is already restarting"
            )
        elif now - _last_disconnect_restart_at < _DISCONNECT_RESTART_COOLDOWN_SEC:
            logger.warning(
                "Skipping disconnect restart fallback — cooldown %.0fs remaining",
                _DISCONNECT_RESTART_COOLDOWN_SEC - (now - _last_disconnect_restart_at),
            )
        else:
            _last_disconnect_restart_at = now
            # Core down / API unreachable — a rebuild + restart is the only way to
            # converge. Issued once for the whole batch (never once per user).
            flush_live_serving(force_restart=True)
    else:
        logger.debug(
            "Hot disconnect unavailable; restart fallback disabled for this batch"
        )

    try:
        from app.db import GetDB
        from app.wireguard.wg_manager import toggle_peer

        with GetDB() as db:
            for dbuser in users:
                try:
                    toggle_peer(db, dbuser.id, active=False)
                except Exception:
                    logger.debug("WG peer toggle skipped for user %s", dbuser.id, exc_info=True)
    except Exception:
        logger.debug("WG peer toggle during disconnect skipped", exc_info=True)

    try:
        from app.singbox.operations import sync_user_change

        sync_user_change()
    except Exception:
        logger.debug("sing-box sync during disconnect skipped", exc_info=True)

    return True


def disconnect_user_everywhere(dbuser: User) -> None:
    """Drop a single user from every live core/node path (Xray, SS, sing-box, WG)."""
    disconnect_users_everywhere([dbuser])


def disconnect_limited_users_if_due(dbusers: Sequence[User]) -> bool:
    """Safety-net disconnect for already-``limited`` users, rate-limited per user.

    The review job would otherwise re-issue a disconnect for *every* limited
    user on *every* 5s tick. Since a limited user is already absent from the
    generated config, re-asserting the (now live handler-API) disconnect only
    needs to happen rarely. Fire at most once per
    ``_LIMITED_REDISCONNECT_COOLDOWN_SEC`` per user and collapse everything due
    this tick into a single batched pass.
    """
    now = time.monotonic()
    due: List[User] = []
    for dbuser in dbusers:
        if now >= _limited_redisconnect_after.get(dbuser.id, 0.0):
            _limited_redisconnect_after[dbuser.id] = now + _LIMITED_REDISCONNECT_COOLDOWN_SEC
            due.append(dbuser)
    return disconnect_users_everywhere(due, allow_restart=False)


def enforce_disconnect_for_non_billable(db, uids: Iterable[int]) -> None:
    """Verified enforcement for non-billable users that still emit traffic.

    Called every usage tick with the uids that reported traffic. For any user
    that is no longer billable (limited/expired/disabled) we first re-assert the
    live handler-API remove (cheap, no restart) — this alone stops all *new*
    connections. Only when a user keeps leaking on an already-established
    session for ``LIMITED_LEAK_RESTART_STREAK`` *consecutive* ticks do we
    escalate to a single batched core restart to hard-cut the stubborn session.
    A user who stops leaking (session closed) has their streak cleared, so a
    naturally-closing connection never triggers a restart. This is the
    "better than 3x-ui" guarantee: 3x-ui removes the user and then lets any
    established session keep transferring indefinitely.

    ``db`` may be an open session (tests) or ``None`` (scheduler). The query is
    always finished and copied into plain objects *before* any network I/O so a
    hung disconnect cannot leave Postgres idle-in-transaction.
    """
    if not uids:
        return

    def _load(session) -> List[Tuple[int, str, UserStatus]]:
        return [
            (int(row[0]), str(row[1]), row[2])
            for row in session.query(User.id, User.username, User.status)
            .filter(
                User.id.in_(list(uids)),
                User.status.notin_((UserStatus.active, UserStatus.on_hold)),
            )
            .all()
        ]

    if db is None:
        from app.db import GetDB

        with GetDB() as session:
            loaded = _load(session)
    else:
        loaded = _load(db)

    if not loaded:
        # Nobody non-billable is leaking this tick — clear all streaks.
        _leak_streak.clear()
        return

    from types import SimpleNamespace

    from config import LIMITED_LEAK_RESTART_STREAK

    rows = [
        SimpleNamespace(id=uid, username=username, status=status)
        for uid, username, status in loaded
    ]

    leaking_ids = {dbuser.id for dbuser in rows}
    # Decay streaks for users who stopped leaking since the last tick.
    for uid in list(_leak_streak.keys()):
        if uid not in leaking_ids:
            del _leak_streak[uid]

    # Step 1: cheap, restart-free re-assert of the hot remove for every leaker.
    try:
        from app.xray.serving import hot_disconnect_users

        hot_disconnect_users(rows)
    except Exception:
        logger.debug("Hot re-assert during non-billable enforcement skipped", exc_info=True)

    # Step 2: escalate only genuinely stubborn sessions (bounded, cooldown-gated).
    now = time.monotonic()
    to_hard_cut: List = []
    for dbuser in rows:
        streak = _leak_streak.get(dbuser.id, 0) + 1
        _leak_streak[dbuser.id] = streak
        if LIMITED_LEAK_RESTART_STREAK <= 0 or streak < LIMITED_LEAK_RESTART_STREAK:
            continue
        if now < _force_disconnect_after.get(dbuser.id, 0):
            continue
        _force_disconnect_after[dbuser.id] = now + _FORCE_DISCONNECT_COOLDOWN_SEC
        _leak_streak.pop(dbuser.id, None)
        logger.warning(
            'User "%s" (%s) kept transferring on an established session after hot '
            "remove — escalating to a batched core restart to hard-cut it",
            dbuser.username,
            dbuser.status,
        )
        to_hard_cut.append(dbuser)

    if to_hard_cut:
        global _last_disconnect_restart_at
        from app import xray

        now2 = time.monotonic()
        if getattr(xray.core, "restarting", False):
            logger.warning("Skipping leak-escalation restart — core already restarting")
        elif now2 - _last_disconnect_restart_at < _DISCONNECT_RESTART_COOLDOWN_SEC:
            logger.warning("Skipping leak-escalation restart — cooldown active")
        else:
            _last_disconnect_restart_at = now2
            flush_live_serving(force_restart=True)


def clamp_usage_entries(
    users_usage: Sequence[dict],
    rows: Iterable[Tuple[int, int, Optional[int]]],
) -> Tuple[List[dict], List[int]]:
    """Clamp per-user deltas. Returns (clamped_entries, uids_that_hit_limit)."""
    meta = {int(uid): (int(used or 0), limit) for uid, used, limit in rows}
    out: List[dict] = []
    hit: List[int] = []
    for entry in users_usage:
        uid = int(entry["uid"])
        used, limit = meta.get(uid, (0, None))
        raw = int(entry["value"])
        value = clamp_usage_delta(used, limit, raw)
        if limit and value > 0 and used + value >= limit:
            hit.append(uid)
        if value > 0:
            out.append({"uid": uid, "value": value})
    return out, hit
