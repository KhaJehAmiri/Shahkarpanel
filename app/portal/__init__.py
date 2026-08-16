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


def compute_renewal_data_limit(user: User, plan: Plan) -> Optional[int]:
    """Data limit after a portal/admin plan renew.

    - Volume → volume: purchased bytes are *added* to unused remaining quota.
    - Unlimited → volume: start a fresh package (no carry-over).
    - Any → unlimited: ``None`` (unlimited); prior volume is not kept.
    """
    from app.billing.reseller_tariffs import (
        is_unlimited_data_limit,
        normalize_data_limit,
    )

    plan_limit = normalize_data_limit(plan.data_limit)
    if plan_limit is None:
        return None
    if is_unlimited_data_limit(user.data_limit):
        return plan_limit
    remaining = max(0, int(user.data_limit or 0) - int(user.used_traffic or 0))
    return int(plan_limit) + remaining


def apply_plan_to_user(db: Session, user: User, plan: Plan) -> User:
    """Immediately renew a user from a commercial plan.

    Volume renewals keep unused remaining traffic and add the new plan package
    on top (then archive/reset the usage counter so the UI shows a fresh
    period against the combined cap). Converting unlimited → volume starts
    from zero with only the new package. Unlimited plans never fall back to
    a previous volume cap.
    """
    from app.db import crud
    from app.billing.reseller_tariffs import resolve_locked_limits_for_admin

    new_expire = compute_renewal_expire(user, plan)
    # Must run before reset_user_data_usage — remaining depends on current used.
    new_data_limit = compute_renewal_data_limit(user, plan)

    used = int(user.used_traffic or 0)
    overage = int(getattr(user, "overage_traffic", 0) or 0)
    if used > 0 or overage > 0:
        user = crud.reset_user_data_usage(db, user)

    device_limit = plan.device_limit
    speed_up = None
    speed_down = None
    billing_admin = None
    if getattr(user, "admin_id", None):
        billing_admin = crud.get_admin_by_id(db, user.admin_id)
    locks = resolve_locked_limits_for_admin(
        db, billing_admin, commercial_plan=plan
    )
    if "device_limit" in locks:
        device_limit = locks["device_limit"]
    if "speed_limit_up" in locks:
        speed_up = locks["speed_limit_up"]
    if "speed_limit_down" in locks:
        speed_down = locks["speed_limit_down"]

    modify_kwargs = dict(
        expire=new_expire if new_expire is not None else 0,
        data_limit=new_data_limit if new_data_limit is not None else 0,
        status=UserStatusModify.active,
        proxies={},
        inbounds={},
        device_limit=device_limit,
    )
    if speed_up is not None:
        modify_kwargs["speed_limit_up"] = speed_up
    if speed_down is not None:
        modify_kwargs["speed_limit_down"] = speed_down
    modify = UserModify(**modify_kwargs)
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
    """Clone protocol types from the portal login user (fresh credentials).

    Only keep protocols that this panel can actually serve. Copying Shadowsocks
    (or other) from an owner when the panel has no matching inbound produces
    ``UserCreate`` validation errors on purchase approve
    (``Shadowsocks inbounds cannot be empty``).
    """
    from app import xray
    from app.models.proxy import ProxyTypes
    from app.xray.inbound_match import inbound_matches_proxy

    _no_inbound_required = {
        ProxyTypes.WireGuard,
        ProxyTypes.Hysteria2,
        ProxyTypes.TUIC,
        ProxyTypes.AnyTLS,
    }

    ur = UserResponse.model_validate(owner, context={"skip_default_links": True})
    proxies: dict = {}
    inbounds: dict = {}
    owner_inbounds = ur.inbounds or {}

    for ptype in ur.proxies or {}:
        ptype_enum = ptype if isinstance(ptype, ProxyTypes) else ProxyTypes(str(ptype))
        if ptype_enum in _no_inbound_required:
            proxies[ptype] = {}
            tags = list(owner_inbounds.get(ptype) or [])
            if tags:
                inbounds[ptype] = tags
            continue

        available = list(
            xray.config.product_inbounds_for_type(ptype_enum)
            or xray.config.inbounds_by_protocol.get(ptype_enum.value, [])
            or []
        )
        if not available:
            # Panel has no inbound for this protocol — skip it.
            continue

        settings: dict = {}
        if ptype_enum == ProxyTypes.Shadowsocks:
            method = (available[0].get("ss_method") or "").strip()
            if method:
                settings["method"] = method

        # Keep owner tags that still exist and match cipher family; otherwise
        # omit so UserCreate auto-selects compatible inbounds.
        kept = [
            tag
            for tag in (owner_inbounds.get(ptype) or [])
            if tag in xray.config.inbounds_by_tag
            and inbound_matches_proxy(ptype, tag, settings)
        ]
        proxies[ptype] = settings
        if kept:
            inbounds[ptype] = kept

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
    import logging

    from app.db import crud
    from app import xray
    from app.subscription.panel_balance import (
        bind_user_to_panel,
        default_panel_for_create,
    )
    from sqlalchemy.exc import IntegrityError

    logger = logging.getLogger("uvicorn.error")

    from app.portal.username_check import require_available_portal_username

    username = require_available_portal_username(db, username)

    proxies, inbounds = _protocol_blueprint_from_owner(owner)
    expire = compute_fresh_expire(plan)
    data_limit = plan.data_limit if plan.data_limit is not None else 0

    device_limit = plan.device_limit
    speed_up = None
    speed_down = None
    try:
        from app.billing.reseller_tariffs import resolve_locked_limits_for_admin

        owner_admin = None
        if owner.admin_id:
            owner_admin = crud.get_admin_by_id(db, owner.admin_id)
        locks = resolve_locked_limits_for_admin(
            db, owner_admin, commercial_plan=plan
        )
        if "device_limit" in locks:
            device_limit = locks["device_limit"]
        if "speed_limit_up" in locks:
            speed_up = locks["speed_limit_up"]
        if "speed_limit_down" in locks:
            speed_down = locks["speed_limit_down"]
    except Exception:
        pass

    try:
        create_kwargs = dict(
            username=username,
            proxies=proxies,
            inbounds=inbounds,
            expire=expire or 0,
            data_limit=data_limit or 0,
            status=UserStatusCreate.active,
            device_limit=device_limit,
            portal_enabled=False,
        )
        if speed_up is not None:
            create_kwargs["speed_limit_up"] = speed_up
        if speed_down is not None:
            create_kwargs["speed_limit_down"] = speed_down
        new_user = UserCreate(**create_kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    admin = None
    if owner.admin_id:
        admin = crud.get_admin_by_id(db, owner.admin_id)

    # Least-loaded p1…p9 (or reseller branding) — same balancer as admin create.
    # Do not rewrite the customer-chosen username with a pN_ prefix.
    panel_ep = default_panel_for_create(db, admin)

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

    if panel_ep is not None:
        try:
            bind_user_to_panel(
                db,
                user_id=dbuser.id,
                username=dbuser.username,
                endpoint=panel_ep,
                source="portal-purchase",
            )
            logger.info(
                'Portal account "%s" bound to subscription panel %s',
                dbuser.username,
                panel_ep.slug,
            )
        except Exception as exc:
            logger.warning(
                'Portal account "%s" created but panel bind failed (%s): %s',
                dbuser.username,
                getattr(panel_ep, "slug", "?"),
                exc,
            )

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
