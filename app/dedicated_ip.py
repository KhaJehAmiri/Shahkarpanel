"""Dedicated-IP pool management for Trader accounts (phase B).

A :class:`DedicatedIP` row with ``user_id IS NULL`` is available stock; once
bound to a user it is pinned for the lifetime of the account. The client API
exposes the assigned address so the user can whitelist it on exchanges.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models import DedicatedIP


def add_to_pool(db: Session, address: str, node_id: Optional[int] = None) -> DedicatedIP:
    """Register a new static IP as available stock (idempotent on address)."""
    existing = db.query(DedicatedIP).filter(DedicatedIP.address == address).first()
    if existing:
        if node_id is not None:
            existing.node_id = node_id
            db.commit()
        return existing
    ip = DedicatedIP(address=address, node_id=node_id)
    db.add(ip)
    db.commit()
    db.refresh(ip)
    return ip


def get_for_user(db: Session, user_id: int) -> Optional[DedicatedIP]:
    return db.query(DedicatedIP).filter(DedicatedIP.user_id == user_id).first()


def assign_to_user(db: Session, user_id: int) -> Optional[DedicatedIP]:
    """Bind a free IP to the user (no-op if one is already assigned).

    Returns the assigned IP, or ``None`` when the pool is exhausted.
    """
    current = get_for_user(db, user_id)
    if current:
        return current
    free = (
        db.query(DedicatedIP)
        .filter(DedicatedIP.user_id.is_(None))
        .order_by(DedicatedIP.id)
        .first()
    )
    if not free:
        return None
    free.user_id = user_id
    free.assigned_at = datetime.utcnow()
    db.commit()
    db.refresh(free)
    return free


def release(db: Session, user_id: int) -> bool:
    """Return a user's IP to the pool. Returns ``True`` if one was released."""
    ip = get_for_user(db, user_id)
    if not ip:
        return False
    ip.user_id = None
    ip.assigned_at = None
    db.commit()
    return True


def list_pool(db: Session, only_free: bool = False) -> List[DedicatedIP]:
    query = db.query(DedicatedIP)
    if only_free:
        query = query.filter(DedicatedIP.user_id.is_(None))
    return query.order_by(DedicatedIP.id).all()


def pool_stats(db: Session) -> dict:
    total = db.query(DedicatedIP).count()
    assigned = db.query(DedicatedIP).filter(DedicatedIP.user_id.isnot(None)).count()
    return {"total": total, "assigned": assigned, "free": total - assigned}
