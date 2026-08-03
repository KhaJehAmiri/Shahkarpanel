"""Enforce Family Guard schedules and daily online minutes."""

from __future__ import annotations

from datetime import datetime, timedelta

from app import logger, scheduler
from app.db import GetDB
from app.db.models import User
from app.family_guard.policy import is_enabled
from app.family_guard.schedule import evaluate_access, set_block_state, tick_usage
from app.ha import run_if_leader
from app.models.user import UserStatus
from app.quota import disconnect_users_everywhere, restore_users_everywhere

_JOB_INTERVAL_SEC = 60
_ONLINE_FRESH_SEC = 180


def _is_online(user: User, now: datetime) -> bool:
    online_at = getattr(user, "online_at", None)
    if not online_at:
        return False
    try:
        ts = online_at.replace(tzinfo=None)
    except Exception:
        return False
    return (now - ts) <= timedelta(seconds=_ONLINE_FRESH_SEC)


def enforce_family_guard():
    now = datetime.utcnow()
    to_disconnect: list[int] = []
    to_restore: list[int] = []

    with GetDB() as db:
        rows = (
            db.query(User)
            .filter(
                User.family_controls.isnot(None),
                User.status.in_([UserStatus.active, UserStatus.on_hold]),
            )
            .all()
        )
        dirty = False
        for user in rows:
            controls = user.family_controls
            if not isinstance(controls, dict) or not is_enabled(controls):
                continue

            online = _is_online(user, now)
            updated = tick_usage(
                controls, online=online, interval_seconds=_JOB_INTERVAL_SEC
            )
            allowed, reason = evaluate_access(updated)
            was_blocked = bool(
                (controls.get("runtime") or {}).get("schedule_blocked")
            )
            updated = set_block_state(updated, not allowed, reason)

            if updated != controls:
                user.family_controls = updated
                dirty = True

            if not allowed and not was_blocked:
                to_disconnect.append(user.id)
            elif allowed and was_blocked:
                to_restore.append(user.id)

        if dirty:
            db.commit()

    if to_disconnect:
        try:
            disconnect_users_everywhere(to_disconnect)
            logger.info(
                "Family Guard disconnected %s user(s) (schedule/daily)",
                len(to_disconnect),
            )
        except Exception:
            logger.exception("Family Guard disconnect failed")

    if to_restore:
        try:
            restore_users_everywhere(to_restore)
            logger.info(
                "Family Guard restored %s user(s) after schedule window",
                len(to_restore),
            )
        except Exception:
            logger.exception("Family Guard restore failed")


scheduler.add_job(
    run_if_leader(enforce_family_guard),
    "interval",
    seconds=_JOB_INTERVAL_SEC,
    coalesce=True,
    max_instances=1,
    id="family_guard_enforce",
)
