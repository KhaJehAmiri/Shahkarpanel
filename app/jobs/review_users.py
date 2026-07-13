from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app import logger, scheduler, xray
from app.db import (GetDB, get_notification_reminder, get_users,
                    start_user_expire, reset_user_by_next, update_user_status)
from app.models.user import ReminderType, UserResponse, UserStatus
from app.quota import (
    disconnect_limited_users_if_due,
    disconnect_users_everywhere,
    enforce_usage_cap,
    limit_user_quota,
    reactivate_if_quota_available,
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
        for user in get_users(db, status=UserStatus.active):

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
            elif expired:
                status = UserStatus.expired
                update_user_status(db, user, status)
                expired_users.append(SimpleNamespace(id=int(user.id), username=user.username))
                report.status_change(
                    username=user.username, status=status,
                    user=UserResponse.model_validate(user), user_admin=user.admin,
                )
                logger.info(f"User \"{user.username}\" status changed to {status}")
                continue
            else:
                if WEBHOOK_ADDRESS:
                    add_notification_reminders(db, user, now)
                continue

        for user in get_users(db, status=UserStatus.on_hold):

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

        for user in get_users(db, status=UserStatus.limited):
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
        from app.db import crud

        live_users = []
        with GetDB() as db:
            for uid in next_plan_users + reactivated_ids:
                dbuser = crud.get_user_by_id(db, uid)
                if dbuser is None:
                    continue
                db.expunge(dbuser)
                live_users.append(dbuser)
        for dbuser in live_users:
            try:
                xray.operations.update_user(dbuser)
            except Exception:
                logger.exception('review: live update failed for user id=%s', dbuser.id)

    if activated_on_hold_ids:
        try:
            xray.operations.sync_core_users_async()
        except Exception:
            logger.exception("review: on-hold activation core sync failed")


from app.ha import run_if_leader  # noqa: E402

scheduler.add_job(run_if_leader(review), 'interval',
                  seconds=JOB_REVIEW_USERS_INTERVAL,
                  coalesce=True, max_instances=1)
