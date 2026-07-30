from collections import deque
from datetime import datetime as dt
from enum import Enum
from typing import Type

from pydantic import BaseModel

from config import WEBHOOK_ADDRESS
from app.models.admin import Admin
from app.models.user import UserResponse

queue = deque()


class Notification(BaseModel):
    class Type(str, Enum):
        user_created = "user_created"
        user_updated = "user_updated"
        user_deleted = "user_deleted"
        user_limited = "user_limited"
        user_expired = "user_expired"
        user_enabled = "user_enabled"
        user_disabled = "user_disabled"
        data_usage_reset = "data_usage_reset"
        data_reset_by_next = "data_reset_by_next"
        subscription_revoked = "subscription_revoked"

        reached_usage_percent = "reached_usage_percent"
        reached_days_left = "reached_days_left"

    enqueued_at: float = dt.utcnow().timestamp()
    send_at: float = dt.utcnow().timestamp()
    tries: int = 0


class UserNotification(Notification):
    username: str


class ReachedUsagePercent(UserNotification):
    action: Notification.Type = Notification.Type.reached_usage_percent
    user: UserResponse
    used_percent: float


class ReachedDaysLeft(UserNotification):
    action: Notification.Type = Notification.Type.reached_days_left
    user: UserResponse
    days_left: int


class UserCreated(UserNotification):
    action: Notification.Type = Notification.Type.user_created
    by: Admin
    user: UserResponse


class UserUpdated(UserNotification):
    action: Notification.Type = Notification.Type.user_updated
    by: Admin
    user: UserResponse


class UserDeleted(UserNotification):
    action: Notification.Type = Notification.Type.user_deleted
    by: Admin


class UserLimited(UserNotification):
    action: Notification.Type = Notification.Type.user_limited
    user: UserResponse


class UserExpired(UserNotification):
    action: Notification.Type = Notification.Type.user_expired
    user: UserResponse


class UserEnabled(UserNotification):
    action: Notification.Type = Notification.Type.user_enabled
    by: Admin | None = None
    user: UserResponse


class UserDisabled(UserNotification):
    action: Notification.Type = Notification.Type.user_disabled
    by: Admin
    user: UserResponse
    reason: str | None = None


class UserDataUsageReset(UserNotification):
    action: Notification.Type = Notification.Type.data_usage_reset
    by: Admin
    user: UserResponse


class UserDataResetByNext(UserNotification):
    action: Notification.Type = Notification.Type.data_usage_reset
    user: UserResponse


class UserSubscriptionRevoked(UserNotification):
    action: Notification.Type = Notification.Type.subscription_revoked
    by: Admin
    user: UserResponse


_PUSH_COPY = {
    "user_limited": ("Data limit reached", "Your account has reached its data limit."),
    "user_expired": ("Subscription expired", "Your subscription has expired."),
    "reached_usage_percent": ("Usage warning", "You have used most of your data allowance."),
    "reached_days_left": ("Expiry reminder", "Your subscription is ending soon."),
    "subscription_revoked": ("Subscription revoked", "Your subscription link was revoked."),
    "user_enabled": ("Account enabled", "Your account is active again."),
    "user_disabled": ("Account disabled", "Your account has been disabled."),
}


def _dispatch_app_push(message: Notification) -> None:
    try:
        from app import feature_flags
        from app.db import GetDB
        from app.db import crud
        from app.push.sender import send_to_user

        if not feature_flags.is_enabled("client_push"):
            return
        username = getattr(message, "username", None)
        if not username:
            return
        action = getattr(message, "action", None)
        key = action.value if action else None
        title, body = _PUSH_COPY.get(key, ("Shahkar", "Account update"))
        with GetDB() as db:
            dbuser = crud.get_user(db, username)
            if dbuser and dbuser.portal_enabled:
                send_to_user(db, dbuser.id, title, body, data={"event": key or "update"})
    except Exception:
        pass


def notify(message: Type[Notification]) -> None:
    # Publish to the event bus first so all consumers (plugins, rules, audit
    # log, Redis fan-out) receive the event regardless of webhook config.
    try:
        from app.events import publish_notification
        publish_notification(message)
    except Exception:
        pass

    _dispatch_app_push(message)

    # Preserve legacy webhook delivery behaviour.
    if WEBHOOK_ADDRESS:
        queue.append(message)
