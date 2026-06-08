from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app import logger, xray
from app.db import Session, crud, get_db
from app.dependencies import get_expired_users_list, get_validated_user, validate_dates
from app.models.admin import Admin
from app.models.proxy import ProxyTypes
from app.models.user import (
    UserCreate,
    UserModify,
    UserResponse,
    UsersResponse,
    UserStatus,
    UserStatusCreate,
    UsersUsagesResponse,
    UserUsagesResponse,
)
from app.rbac import require_permission
from app.utils import report, responses

router = APIRouter(tags=["User"], prefix="/api", responses={401: responses._401})


class UserFromTemplateCreate(BaseModel):
    username: str
    template_id: int
    status: UserStatusCreate = UserStatusCreate.active  # noqa: F821


def _ensure_protocol_enabled(proxy_type, db: Session) -> None:
    """A protocol is usable when it has at least one inbound (Xray) or, for
    WireGuard (which is not an Xray inbound), at least one configured WG node."""
    if proxy_type == ProxyTypes.WireGuard:
        if not crud.get_wireguard_nodes(db):
            raise HTTPException(
                status_code=400,
                detail="WireGuard has no configured node on your server",
            )
        return
    if not xray.config.inbounds_by_protocol.get(proxy_type):
        raise HTTPException(
            status_code=400,
            detail=f"Protocol {proxy_type} is disabled on your server",
        )


@router.post("/user", response_model=UserResponse, responses={400: responses._400, 409: responses._409})
def add_user(
    new_user: UserCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """
    Add a new user

    - **username**: 3 to 32 characters, can include a-z, 0-9, and underscores.
    - **status**: User's status, defaults to `active`. Special rules if `on_hold`.
    - **expire**: UTC timestamp for account expiration. Use `0` for unlimited.
    - **data_limit**: Max data usage in bytes (e.g., `1073741824` for 1GB). `0` means unlimited.
    - **data_limit_reset_strategy**: Defines how/if data limit resets. `no_reset` means it never resets.
    - **proxies**: Dictionary of protocol settings (e.g., `vmess`, `vless`).
    - **inbounds**: Dictionary of protocol tags to specify inbound connections.
    - **note**: Optional text field for additional user information or notes.
    - **on_hold_timeout**: UTC timestamp when `on_hold` status should start or end.
    - **on_hold_expire_duration**: Duration (in seconds) for how long the user should stay in `on_hold` status.
    - **next_plan**: Next user plan (resets after use).
    """

    # TODO expire should be datetime instead of timestamp

    for proxy_type in new_user.proxies:
        _ensure_protocol_enabled(proxy_type, db)

    try:
        dbuser = crud.create_user(
            db,
            new_user,
            admin=crud.get_admin(db, admin.username),
        )
    except ValueError as exc:
        if "user limit" in str(exc).lower():
            raise HTTPException(status_code=403, detail=str(exc))
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")

    bg.add_task(xray.operations.add_user, dbuser=dbuser)
    user = UserResponse.model_validate(dbuser)
    report.user_created(user=user, user_id=dbuser.id, by=admin, user_admin=dbuser.admin)
    logger.info(f'New user "{dbuser.username}" added')
    return user


@router.post(
    "/user/from-template",
    response_model=UserResponse,
    responses={400: responses._400, 403: responses._403, 404: responses._404, 409: responses._409},
)
def add_user_from_template(
    body: UserFromTemplateCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Create a user from a saved template (prefix/suffix, limits, inbounds)."""
    from app.models.user_template import UserTemplateResponse

    db_tpl = crud.get_user_template(db, body.template_id)
    if db_tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    tpl = UserTemplateResponse.model_validate(db_tpl)

    username = body.username.strip()
    if db_tpl.username_prefix:
        username = f"{db_tpl.username_prefix}{username}"
    if db_tpl.username_suffix:
        username = f"{db_tpl.username_suffix}{username}"

    proxies = {ptype: {} for ptype in tpl.inbounds}
    for ptype in proxies:
        _ensure_protocol_enabled(ptype, db)

    expire = 0
    if tpl.expire_duration:
        expire = int(
            (datetime.now(timezone.utc) + timedelta(seconds=tpl.expire_duration)).timestamp()
        )

    new_user = UserCreate(
        username=username,
        proxies=proxies,
        inbounds=tpl.inbounds,
        data_limit=tpl.data_limit if tpl.data_limit is not None else 0,
        expire=expire,
        status=body.status,
    )
    try:
        dbuser = crud.create_user(db, new_user, admin=crud.get_admin(db, admin.username))
    except ValueError as exc:
        if "user limit" in str(exc).lower():
            raise HTTPException(status_code=403, detail=str(exc))
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")

    bg.add_task(xray.operations.add_user, dbuser=dbuser)
    user = UserResponse.model_validate(dbuser)
    report.user_created(user=user, user_id=dbuser.id, by=admin, user_admin=dbuser.admin)
    logger.info(f'New user "{dbuser.username}" added from template {body.template_id}')
    return user


@router.get("/user/{username}", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def get_user(dbuser: UserResponse = Depends(get_validated_user)):
    """Get user information"""
    return dbuser


@router.put("/user/{username}", response_model=UserResponse, responses={400: responses._400, 403: responses._403, 404: responses._404})
def modify_user(
    modified_user: UserModify,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: UsersResponse = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """
    Modify an existing user

    - **username**: Cannot be changed. Used to identify the user.
    - **status**: User's new status. Can be 'active', 'disabled', 'on_hold', 'limited', or 'expired'.
    - **expire**: UTC timestamp for new account expiration. Set to `0` for unlimited, `null` for no change.
    - **data_limit**: New max data usage in bytes (e.g., `1073741824` for 1GB). Set to `0` for unlimited, `null` for no change.
    - **data_limit_reset_strategy**: New strategy for data limit reset. Options include 'daily', 'weekly', 'monthly', or 'no_reset'.
    - **proxies**: Dictionary of new protocol settings (e.g., `vmess`, `vless`). Empty dictionary means no change.
    - **inbounds**: Dictionary of new protocol tags to specify inbound connections. Empty dictionary means no change.
    - **note**: New optional text for additional user information or notes. `null` means no change.
    - **on_hold_timeout**: New UTC timestamp for when `on_hold` status should start or end. Only applicable if status is changed to 'on_hold'.
    - **on_hold_expire_duration**: New duration (in seconds) for how long the user should stay in `on_hold` status. Only applicable if status is changed to 'on_hold'.
    - **next_plan**: Next user plan (resets after use).

    Note: Fields set to `null` or omitted will not be modified.
    """

    for proxy_type in modified_user.proxies:
        _ensure_protocol_enabled(proxy_type, db)

    old_status = dbuser.status
    dbuser = crud.update_user(db, dbuser, modified_user)
    user = UserResponse.model_validate(dbuser)

    if user.status in [UserStatus.active, UserStatus.on_hold]:
        bg.add_task(xray.operations.sync_core_users_async)
    else:
        xray.operations.remove_user_immediate(dbuser)

    bg.add_task(report.user_updated, user=user, user_admin=dbuser.admin, by=admin)

    logger.info(f'User "{user.username}" modified')

    if user.status != old_status:
        bg.add_task(
            report.status_change,
            username=user.username,
            status=user.status,
            user=user,
            user_admin=dbuser.admin,
            by=admin,
        )
        logger.info(
            f'User "{dbuser.username}" status changed from {old_status} to {user.status}'
        )

    return user


@router.delete("/user/{username}", responses={403: responses._403, 404: responses._404})
def remove_user(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Remove a user"""
    crud.remove_user(db, dbuser)
    bg.add_task(xray.operations.remove_user, dbuser=dbuser)

    bg.add_task(
        report.user_deleted, username=dbuser.username, user_admin=Admin.model_validate(dbuser.admin), by=admin
    )

    logger.info(f'User "{dbuser.username}" deleted')
    return {"detail": "User successfully deleted"}


@router.post("/user/{username}/reset", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def reset_user_data_usage(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Reset user data usage"""
    dbuser = crud.reset_user_data_usage(db=db, dbuser=dbuser)
    if dbuser.status == UserStatus.active:
        bg.add_task(xray.operations.sync_core_users_async)
    elif dbuser.status == UserStatus.on_hold:
        bg.add_task(xray.operations.sync_core_users_async)

    user = UserResponse.model_validate(dbuser)
    bg.add_task(
        report.user_data_usage_reset, user=user, user_admin=dbuser.admin, by=admin
    )

    logger.info(f'User "{dbuser.username}"\'s usage was reset')
    return dbuser


@router.post("/user/{username}/revoke_sub", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def revoke_user_subscription(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Revoke users subscription (Subscription link and proxies)"""
    dbuser = crud.revoke_user_sub(db=db, dbuser=dbuser)

    if dbuser.status in [UserStatus.active, UserStatus.on_hold]:
        bg.add_task(xray.operations.update_user, dbuser=dbuser)
    user = UserResponse.model_validate(dbuser)
    bg.add_task(
        report.user_subscription_revoked, user=user, user_admin=dbuser.admin, by=admin
    )

    logger.info(f'User "{dbuser.username}" subscription revoked')

    return user


@router.get("/users", response_model=UsersResponse, responses={400: responses._400, 403: responses._403, 404: responses._404})
def get_users(
    offset: int = None,
    limit: int = None,
    username: List[str] = Query(None),
    search: Union[str, None] = None,
    owner: Union[List[str], None] = Query(None, alias="admin"),
    status: UserStatus = None,
    sort: str = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:read")),
):
    """Get all users"""
    if sort is not None:
        opts = sort.strip(",").split(",")
        sort = []
        for opt in opts:
            try:
                sort.append(crud.UsersSortingOptions[opt])
            except KeyError:
                raise HTTPException(
                    status_code=400, detail=f'"{opt}" is not a valid sort option'
                )

    users, count = crud.get_users(
        db=db,
        offset=offset,
        limit=limit,
        search=search,
        usernames=username,
        status=status,
        sort=sort,
        admins=owner if admin.is_sudo else [admin.username],
        return_with_count=True,
    )

    return {"users": users, "total": count}


@router.post("/users/reset", responses={403: responses._403, 404: responses._404})
def reset_users_data_usage(
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Reset all users data usage"""
    dbadmin = crud.get_admin(db, admin.username)
    crud.reset_all_users_data_usage(db=db, admin=dbadmin)
    startup_config = xray.config.include_db_users()
    xray.core.restart(startup_config)
    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)
    return {"detail": "Users successfully reset."}


@router.get("/user/{username}/usage", response_model=UserUsagesResponse, responses={403: responses._403, 404: responses._404})
def get_user_usage(
    dbuser: UserResponse = Depends(get_validated_user),
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
):
    """Get users usage"""
    start, end = validate_dates(start, end)

    usages = crud.get_user_usages(db, dbuser, start, end)

    return {"usages": usages, "username": dbuser.username}


class ApplyPlanBody(BaseModel):
    plan_id: int


@router.post("/user/{username}/apply-plan", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def apply_plan_to_user_endpoint(
    body: ApplyPlanBody,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Sell a commercial plan to a user (debits reseller wallet, renews immediately)."""
    from app import billing, feature_flags
    from app.portal import apply_plan_to_user, create_user_order, mark_order_applied
    from app.tenant.plan_ops import assert_plan_accessible, assert_plan_for_user

    if not feature_flags.is_enabled("billing"):
        raise HTTPException(status_code=404, detail="Billing is disabled")

    plan = crud.get_plan_by_id(db, body.plan_id)
    if not plan or not plan.enabled:
        raise HTTPException(status_code=404, detail="Plan not found")

    dbrow = crud.get_user(db, dbuser.username)
    if not dbrow or not dbrow.admin_id:
        raise HTTPException(status_code=400, detail="User has no owning reseller")

    assert_plan_accessible(db, admin, plan)
    assert_plan_for_user(db, dbrow.admin_id, plan)

    price = int(plan.price or 0)
    if price > 0:
        wallet = billing.get_or_create_wallet(db, dbrow.admin_id)
        if wallet.balance < price:
            raise HTTPException(
                status_code=402,
                detail="Insufficient wallet balance — top up before selling this plan",
            )
        billing.add_transaction(
            db,
            dbrow.admin_id,
            -price,
            type="plan_sale",
            description=f"Plan sale for {dbrow.username} — {plan.name}",
            reference=f"user:{dbrow.id}:plan:{plan.id}",
        )

    order = create_user_order(db, dbrow, plan, status="paid")
    dbrow = apply_plan_to_user(db, dbrow, plan)
    mark_order_applied(db, order)

    if dbrow.status in (UserStatus.active, UserStatus.on_hold):
        xray.operations.sync_core_users()

    logger.info(f'User "{dbrow.username}" renewed via plan "{plan.name}" by {admin.username}')
    return UserResponse.model_validate(dbrow)


@router.post("/user/{username}/active-next", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def active_next_plan(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Reset user by next plan"""
    dbuser = crud.reset_user_by_next(db=db, dbuser=dbuser)

    if (dbuser is None or dbuser.next_plan is None):
        raise HTTPException(
            status_code=404,
            detail="User doesn't have next plan",
        )

    if dbuser.status in [UserStatus.active, UserStatus.on_hold]:
        bg.add_task(xray.operations.add_user, dbuser=dbuser)

    user = UserResponse.model_validate(dbuser)
    bg.add_task(
        report.user_data_reset_by_next, user=user, user_admin=dbuser.admin,
    )

    logger.info(f'User "{dbuser.username}"\'s usage was reset by next plan')
    return dbuser


@router.get("/users/usage", response_model=UsersUsagesResponse)
def get_users_usage(
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
    owner: Union[List[str], None] = Query(None, alias="admin"),
    admin: Admin = Depends(require_permission("users:read")),
):
    """Get all users usage"""
    start, end = validate_dates(start, end)

    usages = crud.get_all_users_usages(
        db=db, start=start, end=end, admin=owner if admin.is_sudo else [admin.username]
    )

    return {"usages": usages}


@router.put("/user/{username}/set-owner", response_model=UserResponse)
def set_owner(
    admin_username: str,
    dbuser: UserResponse = Depends(get_validated_user),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Set a new owner (admin) for a user."""
    new_admin = crud.get_admin(db, username=admin_username)
    if not new_admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    dbuser = crud.set_owner(db, dbuser, new_admin)
    user = UserResponse.model_validate(dbuser)

    logger.info(f'{user.username}"owner successfully set to{admin.username}')

    return user


@router.get("/users/expired", response_model=List[str])
def get_expired_users(
    expired_after: Optional[datetime] = Query(None, example="2024-01-01T00:00:00"),
    expired_before: Optional[datetime] = Query(None, example="2024-01-31T23:59:59"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:read")),
):
    """
    Get users who have expired within the specified date range.

    - **expired_after** UTC datetime (optional)
    - **expired_before** UTC datetime (optional)
    - At least one of expired_after or expired_before must be provided for filtering
    - If both are omitted, returns all expired users
    """

    expired_after, expired_before = validate_dates(expired_after, expired_before)

    expired_users = get_expired_users_list(db, admin, expired_after, expired_before)
    return [u.username for u in expired_users]


@router.delete("/users/expired", response_model=List[str])
def delete_expired_users(
    bg: BackgroundTasks,
    expired_after: Optional[datetime] = Query(None, example="2024-01-01T00:00:00"),
    expired_before: Optional[datetime] = Query(None, example="2024-01-31T23:59:59"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """
    Delete users who have expired within the specified date range.

    - **expired_after** UTC datetime (optional)
    - **expired_before** UTC datetime (optional)
    - At least one of expired_after or expired_before must be provided
    """
    expired_after, expired_before = validate_dates(expired_after, expired_before)

    expired_users = get_expired_users_list(db, admin, expired_after, expired_before)
    removed_users = [u.username for u in expired_users]

    if not removed_users:
        raise HTTPException(
            status_code=404, detail="No expired users found in the specified date range"
        )

    crud.remove_users(db, expired_users)

    for removed_user in removed_users:
        logger.info(f'User "{removed_user}" deleted')
        bg.add_task(
            report.user_deleted,
            username=removed_user,
            user_admin=next(
                (u.admin for u in expired_users if u.username == removed_user), None
            ),
            by=admin,
        )

    return removed_users
