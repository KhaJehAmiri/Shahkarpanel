"""Data-limit enforcement helpers (shared by usage recording and review job)."""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app import xray
from app.db import crud
from app.db.models import User
from app.models.user import UserStatus

logger = logging.getLogger("nexus-quota")


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


def limit_user_quota(db: Session, dbuser: User, *, cap_usage: bool = True) -> bool:
    """Move an active user to ``limited`` and stop serving traffic.

    The user row, proxy keys, and WG address are preserved for recharge.
    Only the live peer/inbound is removed until quota is restored.
    """
    if cap_usage:
        enforce_usage_cap(db, dbuser)

    if dbuser.status != UserStatus.active:
        return False
    if not dbuser.data_limit or dbuser.used_traffic < dbuser.data_limit:
        return False

    crud.update_user_status(db, dbuser, UserStatus.limited)
    xray.operations.remove_user_immediate(dbuser)
    logger.info('User "%s" limited at %s/%s bytes', dbuser.username, dbuser.used_traffic, dbuser.data_limit)
    return True


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
