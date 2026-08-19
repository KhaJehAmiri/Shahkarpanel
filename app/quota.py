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

logger = logging.getLogger("shahkar-quota")

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
    """Suspend/restore users based on reseller commercial limits.

    Suspend when either:
      - ``users_usage`` reaches ``max_total_traffic``, or
      - wallet cannot cover currently unbilled GB usage (prepaid billing).

    Restore ``capped_by_reseller`` users when the reseller is under the traffic
    cap **and** the wallet can cover (or there is nothing pending).

    Returns ``(newly_suspended, reactivated_ids)`` so the caller can run the live
    disconnect / core re-sync **after** the DB session closes (mirrors review()).
    """
    from types import SimpleNamespace

    over_ids, _under_cap = resellers_over_traffic_cap(db)
    try:
        from app.billing.usage_billing import resellers_with_unpaid_usage

        wallet_blocked = resellers_with_unpaid_usage(db)
    except Exception:
        logger.debug("wallet insolvency check skipped", exc_info=True)
        wallet_blocked = set()

    suspend_ids = set(over_ids) | set(wallet_blocked)
    newly: List[SimpleNamespace] = []
    reactivated: List[int] = []

    if suspend_ids:
        for u in (
            db.query(User)
            .filter(User.admin_id.in_(suspend_ids), User.status == UserStatus.active)
            .all()
        ):
            u.status = UserStatus.disabled
            u.capped_by_reseller = True
            u.last_status_change = datetime.utcnow()
            newly.append(SimpleNamespace(id=int(u.id), username=u.username))

    # Restore any capped users whose reseller is no longer blocked.
    capped_users = (
        db.query(User)
        .filter(User.capped_by_reseller.is_(True), User.admin_id.isnot(None))
        .all()
    )
    for u in capped_users:
        if u.admin_id in suspend_ids:
            continue
        u.capped_by_reseller = False
        u.last_status_change = datetime.utcnow()
        if quota_exhausted(u):
            u.status = UserStatus.limited
        else:
            u.status = UserStatus.active
            reactivated.append(int(u.id))

    if newly or reactivated:
        db.commit()

    # Peer / Finalmask / sing-box re-enable runs in ``restore_users_everywhere``
    # after the caller closes this session (mirrors disconnect + review()).
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
    allow_restart: bool = False,
) -> bool:
    """Drop a *set* of users from every live path **without disconnecting anyone else**.

    Removes the users through the Xray handler gRPC API (add/remove-user) on the
    main core and every connected node — the same live-mutation path 3x-ui uses
    — so unrelated users keep their sessions.

    Full-core restart is **off by default**. Quota exhaustion and leak cleanup
    must never restart Xray (that flaps every active account). Pass
    ``allow_restart=True`` only for rare admin/migration paths that explicitly
    accept a fleet-wide reconnect.

    Returns True when at least one user was handled.
    """
    global _last_disconnect_restart_at

    users = list(dbusers)
    if not users:
        return False

    from app.runtime_role import owns_control_plane

    if not owns_control_plane():
        from app.sync.outbox import schedule_user_sync_by_id, snapshot_user

        for dbuser in users:
            schedule_user_sync_by_id(
                getattr(dbuser, "id", None),
                "disable",
                payload=snapshot_user(dbuser),
            )
        return True

    hot_ok = False
    try:
        from app.xray.serving import hot_disconnect_users

        hot_ok = hot_disconnect_users(users)
    except Exception:
        logger.exception("Main-core hot disconnect failed")

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
            flush_live_serving(force_restart=True)
    else:
        logger.debug(
            "Hot disconnect unavailable; restart fallback disabled (per-user disable only)"
        )

    try:
        from app.db import GetDB
        from app.wireguard.peer_cache import peer_cache
        from app.wireguard.wg_manager import toggle_peer

        with GetDB() as db:
            for dbuser in users:
                try:
                    toggle_peer(db, dbuser.id, active=False)
                except Exception:
                    logger.debug("WG peer toggle skipped for user %s", dbuser.id, exc_info=True)
            # Dirty only the Finalmask shards those users live on so the
            # hot-replace drops them without rewriting unrelated slots.
            try:
                from app.db.models import Proxy
                from app.models.proxy import ProxyTypes
                from app.wireguard.finalmask_reload import mark_finalmask_slots_dirty
                from app.wireguard.finalmask_shard import user_finalmask_slot

                slots = set()
                uids = [int(u.id) for u in users]
                for proxy in (
                    db.query(Proxy)
                    .filter(Proxy.user_id.in_(uids), Proxy.type == ProxyTypes.WireGuard)
                    .all()
                ):
                    slot = user_finalmask_slot(dict(proxy.settings or {}))
                    if slot is not None:
                        slots.add(int(slot))
                if slots:
                    mark_finalmask_slots_dirty(slots)
            except Exception:
                logger.debug("Finalmask dirty-slot mark skipped", exc_info=True)
        # Drop stale active=True peers from cache before Finalmask rebuild —
        # otherwise urgent hot-replace can bake the disabled user back in.
        peer_cache.invalidate()
    except Exception:
        logger.debug("WG peer toggle during disconnect skipped", exc_info=True)

    try:
        from app.wireguard.finalmask_reload import flush_finalmask_xray_reload
        from app.wireguard.operations import sync_user_change as wg_sync

        # Urgent: skip sequential stats flush + apply nodes in parallel so WG
        # cut latency is close to VLESS hot-remove.
        flush_finalmask_xray_reload(urgent=True)
        wg_sync(immediate=False)
    except Exception:
        logger.debug("WireGuard sync during disconnect skipped", exc_info=True)

    try:
        from app.singbox.operations import sync_user_change

        sync_user_change()
    except Exception:
        logger.debug("sing-box sync during disconnect skipped", exc_info=True)

    return True


def restore_users_everywhere(user_ids: Sequence[int]) -> None:
    """Re-enable Xray / WireGuard / sing-box after a reseller or quota restore.

    Mirrors ``disconnect_users_everywhere``: DB peer flags, Finalmask reload,
    sing-box sync, and per-user Xray hot-push. Callers must invoke this **after**
    the DB session that flipped ``User.status`` has closed/committed.

    ``update_user`` must run while the ORM user is still session-bound
    (``UserResponse`` touches ``usage_logs`` / admin columns).
    """
    from app.db import GetDB, crud
    from app.wireguard.wg_manager import toggle_peer

    ids = [int(uid) for uid in user_ids if uid is not None]
    if not ids:
        return

    with GetDB() as db:
        for uid in ids:
            try:
                toggle_peer(db, uid, active=True)
            except Exception:
                logger.debug("WG peer re-enable skipped for user %s", uid, exc_info=True)

        for uid in ids:
            dbuser = crud.get_user_by_id(db, uid)
            if dbuser is None:
                continue
            if dbuser.status not in (UserStatus.active, UserStatus.on_hold):
                continue
            try:
                from app.xray import operations as xops

                xops.update_user(dbuser)
            except Exception:
                logger.exception(
                    "restore_users_everywhere: Xray update failed for id=%s",
                    uid,
                )

    try:
        from app.wireguard.peer_cache import peer_cache
        from app.wireguard.operations import sync_user_change as wg_sync

        peer_cache.invalidate()
        wg_sync()
    except Exception:
        logger.exception("restore_users_everywhere: WireGuard/Finalmask sync failed")

    try:
        from app.singbox.operations import sync_user_change as singbox_sync

        singbox_sync()
    except Exception:
        logger.exception("restore_users_everywhere: sing-box sync failed")


def reconcile_wg_peer_active_flags(db: Session) -> int:
    """Fix ``wg_peers.active`` drift vs billable user status. Returns count fixed."""
    from sqlalchemy import and_, or_

    from app.db.models import WgPeer
    from app.wireguard.wg_manager import SERVED_STATUSES, toggle_peer, wg_peer_want_active

    served = list(SERVED_STATUSES)
    mismatched = (
        db.query(WgPeer.user_id)
        .join(User, User.id == WgPeer.user_id)
        .filter(
            or_(
                and_(User.status.in_(served), WgPeer.active.is_(False)),
                and_(User.status.notin_(served), WgPeer.active.is_(True)),
            )
        )
        .all()
    )
    # Also catch active peers that exclusivity is holding off.
    held_active = (
        db.query(WgPeer.user_id)
        .join(User, User.id == WgPeer.user_id)
        .filter(
            User.status.in_(served),
            WgPeer.active.is_(True),
            User.device_conn_hold.isnot(None),
        )
        .all()
    )
    uids = {int(uid) for (uid,) in mismatched} | {int(uid) for (uid,) in held_active}
    fixed = 0
    for uid in uids:
        user = db.query(User).filter(User.id == uid).first()
        want = wg_peer_want_active(user)
        try:
            peer = db.query(WgPeer).filter(WgPeer.user_id == uid).first()
            if peer is None or peer.active == want:
                continue
            if toggle_peer(db, int(uid), active=want):
                fixed += 1
        except Exception:
            logger.debug(
                "reconcile_wg_peer_active_flags skipped user %s",
                uid,
                exc_info=True,
            )
    return fixed


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
    that is no longer billable (limited/expired/disabled) we re-assert the
    live handler-API remove (cheap, no restart) so *new* connections stay
    blocked. Stubborn established sessions are re-asserted per-user via
    ``disconnect_users_everywhere`` (WG peer off + Finalmask dirty) — never
    a full-core restart, which would flap every active account.

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

    # Step 2: stubborn leakers used to escalate to a full-core restart, which
    # disconnected every active user. That path is retired — keep re-asserting
    # hot remove + WG peer disable only (see disconnect_users_everywhere).
    for dbuser in rows:
        streak = _leak_streak.get(dbuser.id, 0) + 1
        _leak_streak[dbuser.id] = streak
        if LIMITED_LEAK_RESTART_STREAK <= 0:
            continue
        if streak < LIMITED_LEAK_RESTART_STREAK:
            continue
        if time.monotonic() < _force_disconnect_after.get(dbuser.id, 0):
            continue
        _force_disconnect_after[dbuser.id] = time.monotonic() + _FORCE_DISCONNECT_COOLDOWN_SEC
        _leak_streak.pop(dbuser.id, None)
        logger.warning(
            'User "%s" (%s) kept transferring after hot remove — re-asserting '
            "per-user disable (no core restart)",
            dbuser.username,
            dbuser.status,
        )
        try:
            disconnect_users_everywhere([dbuser], allow_restart=False)
        except Exception:
            logger.debug("stubborn-leak per-user disable skipped", exc_info=True)


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
