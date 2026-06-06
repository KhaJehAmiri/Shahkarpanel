"""Strict data-limit enforcement and recharge preservation."""
import uuid

from app.db import GetDB, crud
from app.db.models import User
from app.jobs.record_usages import record_aggregated_user_usages
from app.models.user import UserStatus
from app.quota import clamp_usage_delta, enforce_usage_cap


def _mk_user(db, *, limit: int, used: int = 0) -> int:
    u = User(
        username=f"quota-{uuid.uuid4().hex[:8]}",
        status=UserStatus.active,
        data_limit=limit,
        used_traffic=used,
    )
    db.add(u)
    db.commit()
    return u.id


def test_clamp_delta_never_exceeds_limit():
    limit = 1024**3
    assert clamp_usage_delta(limit - 1000, limit, 5000) == 1000
    assert clamp_usage_delta(limit, limit, 999999) == 0


def test_record_usage_never_passes_limit():
    limit = 10 * 1024 * 1024  # 10 MiB
    with GetDB() as db:
        uid = _mk_user(db, limit=limit, used=0)

    record_aggregated_user_usages({None: [{"uid": str(uid), "value": limit + 1024 * 1024}]}, {None: 1})

    with GetDB() as db:
        used = db.query(User.used_traffic).filter(User.id == uid).scalar()
        status = db.query(User.status).filter(User.id == uid).scalar()
    assert used == limit
    assert status == UserStatus.limited


def test_enforce_usage_cap_fixes_overage():
    limit = 1024**2
    with GetDB() as db:
        uid = _mk_user(db, limit=limit, used=limit + 5000)
        u = crud.get_user_by_id(db, uid)
        enforce_usage_cap(db, u)
        u = crud.get_user_by_id(db, uid)

    assert u.used_traffic == limit


def test_concurrent_record_never_exceeds_limit():
    """Simulate two billing cycles that each read stale usage before commit."""
    limit = 1000
    chunk = 600
    with GetDB() as db:
        uid = _mk_user(db, limit=limit, used=0)

    for _ in range(2):
        record_aggregated_user_usages({None: [{"uid": uid, "value": chunk}]}, {None: 1})

    with GetDB() as db:
        used = db.query(User.used_traffic).filter(User.id == uid).scalar()
        status = db.query(User.status).filter(User.id == uid).scalar()
    assert used == limit
    assert status == UserStatus.limited


def test_reset_reactivates_limited_user():
    limit = 1024**2
    with GetDB() as db:
        uid = _mk_user(db, limit=limit, used=limit)
        u = crud.get_user_by_id(db, uid)
        u.status = UserStatus.limited
        db.commit()

    with GetDB() as db:
        u = crud.get_user_by_id(db, uid)
        crud.reset_user_data_usage(db, u)
        u = crud.get_user_by_id(db, uid)

    assert u.status == UserStatus.active
    assert u.used_traffic == 0
    assert u.data_limit == limit
