from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app import logger, scheduler, xray
from app.db import (GetDB, get_notification_reminder, get_users,
                    start_user_expire, reset_user_by_next, update_user_status)
from app.db.models import User
from app.models.user import ReminderType, UserResponse, UserStatus
from app.quota import (
    disconnect_limited_users_if_due,
    disconnect_users_everywhere,
    enforce_reseller_traffic_caps,
    enforce_usage_cap,
    limit_user_quota,
    reactivate_if_quota_available,
    reconcile_wg_peer_active_flags,
    restore_users_everywhere,
)
from app.utils import report
from app.utils.helpers import (calculate_expiration_days,
                               calculate_usage_percent)
from config import (JOB_REVIEW_USERS_INTERVAL, NOTIFY_DAYS_LEFT,
                    NOTIFY_REACHED_USAGE_PERCENT, WEBHOOK_ADDRESS)

if TYPE_CHECKING:
    from app.db.models import User


def add_notification_reminders(db: Session, user: "User", now: datetime = datetime.utcnow()) -> None:
    if user.data_limit:
        usage_percent = calculate_usage_percent(user.used_traffic, user.data_limit)

        for percent in sorted(NOTIFY_REACHED_USAGE_PERCENT, reverse=True):
            if usage_percent >= percent:
                if not get_notification_reminder(db, user.id, ReminderType.data_usage, threshold=percent):
                    report.data_usage_percent_reached(
                        db, usage_percent, UserResponse.model_validate(user),
                        user.id, user.expire, threshold=percent
                    )
                break

    if user.expire:
        expire_days = calculate_expiration_days(user.expire)

        for days_left in sorted(NOTIFY_DAYS_LEFT):
            if expire_days <= days_left:
                if not get_notification_reminder(db, user.id, ReminderType.expiration_date, threshold=days_left):
                    report.expire_days_reached(
                        db, expire_days, UserResponse.model_validate(user),
                        user.id, user.expire, threshold=days_left
                    )
                break


def reset_user_by_next_report(db: Session, user: "User"):
    user = reset_user_by_next(db, user)
    # Caller must run live sync *after* the DB session closes.
    return user


def review():
    now = datetime.utcnow()
    now_ts = now.timestamp()

    # Network / core ops collected here and run only after GetDB closes.
    # Holding the review transaction open across disconnect/restart used to
    # idle-in-transaction for minutes and freeze Overview online stats
    # (record_user_usages / review both max_instances=1).
    newly_limited: list[SimpleNamespace] = []
    expired_users: list[SimpleNamespace] = []
    next_plan_users: list[int] = []
    reactivated_ids: list[int] = []
    activated_on_hold_ids: list[int] = []
    limited_safety_net: list[SimpleNamespace] = []

    with GetDB() as db:
        # Active users that hit quota or expiry — never scan the whole table.
        active_due = (
            db.query(User)
            .options(joinedload(User.admin), joinedload(User.next_plan))
            .filter(
                User.status == UserStatus.active,
                or_(
                    and_(
                        User.data_limit.isnot(None),
                        User.data_limit > 0,
                        User.used_traffic >= User.data_limit,
                    ),
                    and_(
                        User.expire.isnot(None),
                        User.expire > 0,
                        User.expire <= int(now_ts),
                    ),
                ),
            )
            .yield_per(500)
        )
        for user in active_due:
            limited = user.data_limit and user.used_traffic >= user.data_limit
            expired = user.expire and user.expire <= now_ts

            if (limited or expired) and user.next_plan is not None:
                if user.next_plan.fire_on_either or (limited and expired):
                    reset_user_by_next_report(db, user)
                    next_plan_users.append(int(user.id))
                    continue

            if limited:
                if limit_user_quota(db, user, cap_usage=True, disconnect=False):
                    newly_limited.append(SimpleNamespace(id=int(user.id), username=user.username))
                    report.status_change(
                        username=user.username,
                        status=UserStatus.limited,
                        user=UserResponse.model_validate(user),
                        user_admin=user.admin,
                    )
                continue
            if expired:
                status = UserStatus.expired
                update_user_status(db, user, status)
                expired_users.append(SimpleNamespace(id=int(user.id), username=user.username))
                report.status_change(
                    username=user.username, status=status,
                    user=UserResponse.model_validate(user), user_admin=user.admin,
                )
                logger.info(f"User \"{user.username}\" status changed to {status}")
                continue

        # Webhook reminders: only users near expiry OR near usage percent.
        if WEBHOOK_ADDRESS:
            max_days = max(NOTIFY_DAYS_LEFT) if NOTIFY_DAYS_LEFT else 0
            soon = int(now_ts) + int(max_days) * 86400 if max_days else 0
            min_pct = min(NOTIFY_REACHED_USAGE_PERCENT) if NOTIFY_REACHED_USAGE_PERCENT else 80
            # used_traffic >= data_limit * min_pct / 100
            near_usage = and_(
                User.data_limit.isnot(None),
                User.data_limit > 0,
                User.used_traffic >= (User.data_limit * int(min_pct)) / 100,
            )
            clauses = [near_usage]
            if soon:
                clauses.append(
                    and_(User.expire.isnot(None), User.expire > 0, User.expire <= soon)
                )
            remind_q = (
                db.query(User)
                .options(joinedload(User.admin))
                .filter(User.status == UserStatus.active, or_(*clauses))
                .yield_per(500)
            )
            for user in remind_q:
                add_notification_reminders(db, user, now)

        # On-hold: only rows that can activate this tick.
        on_hold_due = (
            db.query(User)
            .options(joinedload(User.admin))
            .filter(
                User.status == UserStatus.on_hold,
                or_(
                    User.online_at.isnot(None),
                    and_(
                        User.on_hold_timeout.isnot(None),
                        User.on_hold_timeout <= now,
                    ),
                ),
            )
            .yield_per(500)
        )
        for user in on_hold_due:
            if user.edit_at:
                base_time = datetime.timestamp(user.edit_at)
            else:
                base_time = datetime.timestamp(user.created_at)

            if user.online_at and base_time <= datetime.timestamp(user.online_at):
                status = UserStatus.active
            elif user.on_hold_timeout and (datetime.timestamp(user.on_hold_timeout) <= (now_ts)):
                status = UserStatus.active
            else:
                continue

            update_user_status(db, user, status)
            start_user_expire(db, user)
            activated_on_hold_ids.append(int(user.id))

            report.status_change(username=user.username, status=status,
                                 user=UserResponse.model_validate(user), user_admin=user.admin)

            logger.info(f"User \"{user.username}\" status changed to {status}")

        # Limited set is typically small; still stream it.
        for user in (
            db.query(User)
            .options(joinedload(User.admin))
            .filter(User.status == UserStatus.limited)
            .yield_per(500)
        ):
            if user.data_limit and user.used_traffic > user.data_limit:
                enforce_usage_cap(db, user)
            elif reactivate_if_quota_available(user):
                db.commit()
                db.refresh(user)
                reactivated_ids.append(int(user.id))
                report.status_change(
                    username=user.username,
                    status=UserStatus.active,
                    user=UserResponse.model_validate(user),
                    user_admin=user.admin,
                )
                logger.info('User "%s" reactivated after quota restored', user.username)
            else:
                limited_safety_net.append(SimpleNamespace(id=int(user.id), username=user.username))

    # --- live paths (no open billing/review transaction) ---
    if newly_limited:
        try:
            disconnect_users_everywhere(newly_limited)
        except Exception:
            logger.exception("review: batched limit disconnect failed")

    if expired_users:
        try:
            disconnect_users_everywhere(expired_users)
        except Exception:
            logger.exception("review: batched expire disconnect failed")

    if limited_safety_net:
        try:
            disconnect_limited_users_if_due(limited_safety_net)
        except Exception:
            logger.exception("review: limited safety-net disconnect failed")

    if next_plan_users or reactivated_ids:
        try:
            restore_users_everywhere(next_plan_users + reactivated_ids)
        except Exception:
            logger.exception("review: quota/next-plan restore live paths failed")

    if activated_on_hold_ids:
        try:
            xray.operations.sync_core_users_async()
        except Exception:
            logger.exception("review: on-hold activation core sync failed")

    # --- reseller total-traffic cap enforcement ---
    # Disable users whose reseller exceeded max_total_traffic, and restore them
    # once the reseller is back under the cap (usage reset or raised limit).
    cap_suspended: list[SimpleNamespace] = []
    cap_reactivated: list[int] = []
    with GetDB() as db:
        try:
            cap_suspended, cap_reactivated = enforce_reseller_traffic_caps(db)
        except Exception:
            logger.exception("review: reseller traffic-cap enforcement failed")

    if cap_suspended:
        try:
            disconnect_users_everywhere(cap_suspended)
        except Exception:
            logger.exception("review: reseller-cap disconnect failed")

    if cap_reactivated:
        try:
            restore_users_everywhere(cap_reactivated)
        except Exception:
            logger.exception("review: reseller-cap restore live paths failed")

    # Safety net: peer.active can drift after cap→limited→recharge paths.
    try:
        with GetDB() as db:
            fixed = reconcile_wg_peer_active_flags(db)
        if fixed:
            from app.wireguard.operations import sync_user_change as wg_sync
            from app.wireguard.peer_cache import peer_cache

            peer_cache.invalidate()
            wg_sync()
            logger.info("review: reconciled %s wg_peers.active flags", fixed)
    except Exception:
        logger.exception("review: wg peer active reconcile failed")


from app.ha import run_if_leader  # noqa: E402

scheduler.add_job(run_if_leader(review), 'interval',
                  seconds=JOB_REVIEW_USERS_INTERVAL,
                  coalesce=True, max_instances=1)
