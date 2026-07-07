"""Per-user continuous online session time limit."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import User


def check_session_limit(dbuser: User) -> None:
    """Raise HTTP 403 when the user exceeds ``session_limit_minutes`` online."""
    from fastapi import HTTPException

    limit_min = getattr(dbuser, "session_limit_minutes", None)
    if not limit_min or limit_min <= 0:
        return
    online_at = getattr(dbuser, "online_at", None)
    if not online_at:
        return
    if datetime.utcnow() - online_at.replace(tzinfo=None) > timedelta(minutes=int(limit_min)):
        raise HTTPException(
            status_code=403,
            detail="Session time limit exceeded; reconnect to continue",
        )


def touch_online(db: Session, dbuser: User) -> None:
    """Refresh ``online_at`` on subscription fetch (starts/resets session clock)."""
    dbuser.online_at = datetime.utcnow()
    db.commit()
