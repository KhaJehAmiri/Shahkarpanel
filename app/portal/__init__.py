"""End-user self-service portal: plan application, renewals, multi-account."""
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from fastapi import HTTPException

from app.db import Session
from app.db.models import Plan, User, UserOrder
from app.models.user import (
    UserCreate,
    UserModify,
    UserResponse,
    UserStatus,
    UserStatusCreate,
    UserStatusModify,
)


def compute_renewal_expire(user: User, plan: Plan) -> Optional[int]:
    """Return new expiry epoch, or None for unlimited."""
    if not plan.duration_days:
        return user.expire
    now = datetime.utcnow().timestamp()
    base = now
    if user.expire and user.expire > now:
        base = float(user.expire)
    return int(base + plan.duration_days * 86400)


def compute_fresh_expire(plan: Plan) -> Optional[int]:
    if not plan.duration_days:
        return None
    return int(datetime.utcnow().timestamp() + plan.duration_days * 86400)


def apply_plan_to_user(db: Session, user: User, plan: Plan) -> User:
    """Immediately renew a user from a commercial plan.

    A plan that carries its own data cap starts a *new* package period, so the
    previous counter is archived into ``user_usage_logs`` first. Without that,
    ``update_user`` keeps the old ``used_traffic`` against the new cap (see
    ``quota.apply_overage_on_recharge``) and a user who already burned the last
    package pays for a renewal yet stays ``limited``.
    """
    from app.db import crud

    new_expire = compute_renewal_expire(user, plan)
    new_data_limit = plan.data_limit if plan.data_limit is not None else user.data_limit

    if plan.data_limit is not None and int(user.used_traffic or 0) > 0:
        user = crud.reset_user_data_usage(db, user)

    modify = UserModify(
        expire=new_expire if new_expire is not None else 0,
        data_limit=new_data_limit if new_data_limit is not None else 0,
        status=UserStatusModify.active,
        proxies={},
        inbounds={},
        device_limit=plan.device_limit,
    )
    user = crud.update_user(db, user, modify)
    return user


def create_user_order(
    db: Session,
    user: User,
    plan: Plan,
    *,
    status: str = "pending",
) -> UserOrder:
    order = UserOrder(
        user_id=user.id,
        plan_id=plan.id,
        amount=plan.price,
        status=status,
    )
    if status == "paid":
        order.paid_at = datetime.utcnow()
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def mark_order_applied(db: Session, order: UserOrder) -> UserOrder:
    order.status = "applied"
    order.applied_at = datetime.utcnow()
    if not order.paid_at:
        order.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return order


def list_owned_accounts(db: Session, owner: User) -> List[User]:
    """Portal login account + every VPN account purchased under it."""
    children = (
        db.query(User)
        .filter(User.portal_owner_user_id == owner.id)
        .order_by(User.id.desc())
        .all()
    )
    return [owner] + children


def assert_can_add_account(db: Session, owner: User) -> None:
    """Cap the accounts one portal login may own.

    Without it a single customer can create/buy accounts until the reseller's
    ``max_users`` quota is gone, locking every other customer out.
    """
    from app import platform_settings

    cap = platform_settings.get_int("portal.max_child_accounts", 20)
    if cap <= 0:
        return
    owned = db.query(User).filter(User.portal_owner_user_id == owner.id).count()
    if owned >= cap:
        raise HTTPException(
            status_code=409,
            detail=f"Account limit reached ({cap}) — contact support to raise it",
        )


def get_owned_account(db: Session, owner: User, username: str) -> User:
    username = (username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username required")
    if owner.username.lower() == username.lower():
        return owner
    child = (
        db.query(User)
        .filter(
            User.username == username,
            User.portal_owner_user_id == owner.id,
        )
        .first()
    )
    if not child:
        raise HTTPException(status_code=404, detail="Account not found")
    return child


def _protocol_blueprint_from_owner(owner: User) -> Tuple[dict, dict]:
    """Clone protocol types/inbounds from the portal login user (fresh credentials)."""
    from app.models.proxy import ProxyTypes

    ur = UserResponse.model_validate(owner, context={"skip_default_links": True})
    proxies: dict = {}
    for ptype in (ur.proxies or {}):
        proxies[ptype] = {}
    inbounds = dict(ur.inbounds or {})
    if not proxies:
        proxies = {ProxyTypes.VLESS: {}}
        inbounds = {}
    return proxies, inbounds


def create_account_from_plan(
    db: Session,
    owner: User,
    plan: Plan,
    username: str,
) -> User:
    """Create a new VPN account owned by the portal login user."""
    from app.db import crud
    from app import xray
    from sqlalchemy.exc import IntegrityError

    username = (username or "").strip().lower()
    if len(username) < 3 or len(username) > 32:
        raise HTTPException(status_code=400, detail="Username must be 3–32 characters")
    if crud.get_user(db, username):
        raise HTTPException(status_code=409, detail="Username already exists")

    proxies, inbounds = _protocol_blueprint_from_owner(owner)
    expire = compute_fresh_expire(plan)
    data_limit = plan.data_limit if plan.data_limit is not None else 0

    try:
        new_user = UserCreate(
            username=username,
            proxies=proxies,
            inbounds=inbounds,
            expire=expire or 0,
            data_limit=data_limit or 0,
            status=UserStatusCreate.active,
            device_limit=plan.device_limit,
            portal_enabled=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    admin = None
    if owner.admin_id:
        admin = crud.get_admin_by_id(db, owner.admin_id)

    try:
        dbuser = crud.create_user(db, new_user, admin=admin)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    dbuser.portal_owner_user_id = owner.id
    # Inherit reseller link from owner even if admin row was missing at create.
    if owner.admin_id and not dbuser.admin_id:
        dbuser.admin_id = owner.admin_id
    db.commit()
    db.refresh(dbuser)

    try:
        xray.operations.add_user(dbuser=dbuser)
    except Exception:
        try:
            xray.operations.sync_core_users()
        except Exception:
            pass

    return dbuser


def delete_owned_account(db: Session, owner: User, username: str) -> None:
    """Delete a child VPN account. Cannot delete the portal login itself."""
    from app.db import crud
    from app import xray

    target = get_owned_account(db, owner, username)
    if target.id == owner.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the portal login account — delete child accounts only",
        )
    # Drop the live session first, then remove the row, and only reconcile the
    # cores afterwards — a sync scheduled before the DELETE would rebuild the
    # config with the account still in it and keep serving traffic.
    try:
        from app.quota import disconnect_users_everywhere

        disconnect_users_everywhere([target])
    except Exception:
        pass
    crud.remove_user(db, target)
    try:
        xray.operations.remove_user(dbuser=target)
    except Exception:
        pass
