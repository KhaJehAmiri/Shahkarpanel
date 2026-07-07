"""End-user self-service portal: plan application and renewal."""
from datetime import datetime, timedelta
from typing import Optional

from app.db import Session
from app.db.models import Plan, User, UserOrder
from app.models.user import UserModify, UserStatusModify


def compute_renewal_expire(user: User, plan: Plan) -> Optional[int]:
    """Return new expiry epoch, or None for unlimited."""
    if not plan.duration_days:
        return user.expire
    now = datetime.utcnow().timestamp()
    base = now
    if user.expire and user.expire > now:
        base = float(user.expire)
    return int(base + plan.duration_days * 86400)


def apply_plan_to_user(db: Session, user: User, plan: Plan) -> User:
    """Immediately renew a user from a commercial plan."""
    from app.db import crud

    new_expire = compute_renewal_expire(user, plan)
    new_data_limit = plan.data_limit if plan.data_limit is not None else user.data_limit

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
