"""Versioned Developer / Bot API (`/api/v2`).

Authenticated via ``X-API-Key`` or a bearer admin JWT. Gated by the ``api_v2``
feature flag. Non-sudo admins only see and mutate their own users / plans /
wallet. Bearer admin tokens bypass API-key scope checks (existing behaviour).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app import feature_flags
from app.api_keys import require_v2_scope
from app.db import Session, crud, get_db
from app.db.models import User
from app.models.admin import Admin
from app.models.user import UserCreate, UserModify, UserResponse, UserStatusCreate
from app.models.user_template import UserTemplateResponse
from app.routers.tenant import BrandingResponse, BrandingUpdate
from app.utils import responses

router = APIRouter(
    tags=["API v2"],
    prefix="/api/v2",
    responses={401: responses._401, 403: responses._403},
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int


class UserV2(BaseModel):
    """Compact user row for list endpoints."""

    username: str
    status: str
    used_traffic: int
    data_limit: Optional[int] = None
    expire: Optional[int] = None
    subscription_url: str = ""
    public_subscription_url: str = ""
    model_config = ConfigDict(from_attributes=True)


class UserFromTemplateBody(BaseModel):
    template_id: int
    username: str
    status: Optional[UserStatusCreate] = None


class ApplyPlanBody(BaseModel):
    plan_id: int


class PlanCreateBody(BaseModel):
    name: str
    price: int = 0
    data_limit: Optional[int] = None
    duration_days: Optional[int] = None
    device_limit: Optional[int] = None
    enabled: bool = True


class PlanModifyBody(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    data_limit: Optional[int] = None
    duration_days: Optional[int] = None
    device_limit: Optional[int] = None
    enabled: Optional[bool] = None


class PlanV2(BaseModel):
    id: int
    name: str
    price: int
    data_limit: Optional[int] = None
    duration_days: Optional[int] = None
    device_limit: Optional[int] = None
    enabled: bool
    tenant_id: Optional[int] = None
    owner_admin_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class WalletV2(BaseModel):
    admin_id: int
    balance: int
    model_config = ConfigDict(from_attributes=True)


class TransactionV2(BaseModel):
    id: int
    admin_id: int
    amount: int
    type: str
    description: Optional[str] = None
    reference: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class TemplateV2(BaseModel):
    id: int
    name: Optional[str] = None
    data_limit: Optional[int] = None
    expire_duration: Optional[int] = None
    username_prefix: Optional[str] = None
    username_suffix: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class WorkspaceV2(BaseModel):
    username: str
    role: str
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    tenant_slug: Optional[str] = None
    users_count: int = 0
    max_users: Optional[int] = None
    nodes_count: int = 0
    max_nodes: Optional[int] = None
    wallet_balance: Optional[int] = None
    wallet_low: bool = False
    wallet_blocked: bool = False
    users_usage: int = 0
    max_total_traffic: Optional[int] = None
    traffic_remaining: Optional[int] = None
    prepaid_traffic_remaining: int = 0
    currency_label: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class UsageV2(BaseModel):
    username: str
    usages: List[Any]


def _require_v2_enabled():
    if not feature_flags.is_enabled("api_v2"):
        raise HTTPException(status_code=404, detail="v2 API is disabled")


def _require_billing_enabled():
    if not feature_flags.is_enabled("billing"):
        raise HTTPException(status_code=404, detail="Billing is disabled")


def _get_owned_user(db: Session, admin: Admin, username: str) -> User:
    dbuser = crud.get_user(db, username)
    if not dbuser:
        raise HTTPException(status_code=404, detail="User not found")
    if not (admin.is_sudo or (dbuser.admin and dbuser.admin.username == admin.username)):
        raise HTTPException(status_code=403, detail="You're not allowed")
    return dbuser


def _to_user_v2(dbuser: User) -> UserV2:
    from app.routers.user import _user_response

    full = _user_response(dbuser, share_links=False)
    return UserV2(
        username=full.username,
        status=full.status.value if hasattr(full.status, "value") else str(full.status),
        used_traffic=full.used_traffic or 0,
        data_limit=full.data_limit,
        expire=full.expire,
        subscription_url=full.subscription_url or "",
        public_subscription_url=full.public_subscription_url or "",
    )


def _full_user(dbuser: User) -> UserResponse:
    from app.routers.user import _user_response

    return _user_response(dbuser, share_links=True)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users", response_model=Page[UserV2])
def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:read")),
):
    _require_v2_enabled()
    from app.db.models import User as DBUser

    query = db.query(DBUser)
    if not admin.is_sudo:
        dbadmin = crud.get_admin(db, admin.username)
        query = query.filter(DBUser.admin_id == (dbadmin.id if dbadmin else -1))
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(DBUser.username.ilike(like))

    total = query.count()
    rows = query.order_by(DBUser.id).offset((page - 1) * size).limit(size).all()
    return Page[UserV2](
        items=[_to_user_v2(u) for u in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/users/{username}", response_model=UserResponse)
def get_user(
    username: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:read")),
):
    _require_v2_enabled()
    return _full_user(_get_owned_user(db, admin, username))


@router.post("/users", response_model=UserResponse, responses={400: responses._400, 409: responses._409})
def create_user(
    body: UserCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:write")),
):
    _require_v2_enabled()
    from app.routers.user import add_user

    return add_user(new_user=body, bg=bg, db=db, admin=admin)


@router.post(
    "/users/from-template",
    response_model=UserResponse,
    responses={400: responses._400, 404: responses._404, 409: responses._409},
)
def create_user_from_template(
    body: UserFromTemplateBody,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:write")),
):
    _require_v2_enabled()
    from app.routers.user import UserFromTemplateCreate, add_user_from_template

    payload: dict = {"template_id": body.template_id, "username": body.username}
    if body.status is not None:
        payload["status"] = body.status
    return add_user_from_template(
        body=UserFromTemplateCreate(**payload),
        bg=bg,
        db=db,
        admin=admin,
    )


@router.put("/users/{username}", response_model=UserResponse)
def modify_user(
    username: str,
    body: UserModify,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:write")),
):
    _require_v2_enabled()
    from app.routers.user import modify_user as dashboard_modify_user

    dbuser = _get_owned_user(db, admin, username)
    return dashboard_modify_user(
        modified_user=body, bg=bg, db=db, dbuser=dbuser, admin=admin
    )


@router.delete("/users/{username}")
def delete_user(
    username: str,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:write")),
):
    _require_v2_enabled()
    from app.routers.user import remove_user

    dbuser = _get_owned_user(db, admin, username)
    return remove_user(bg=bg, db=db, dbuser=dbuser, admin=admin)


@router.post("/users/{username}/reset", response_model=UserResponse)
def reset_user(
    username: str,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:write")),
):
    _require_v2_enabled()
    from app.routers.user import reset_user_data_usage

    dbuser = _get_owned_user(db, admin, username)
    return reset_user_data_usage(bg=bg, db=db, dbuser=dbuser, admin=admin)


@router.post("/users/{username}/rotate-sub", response_model=UserResponse)
def rotate_sub(
    username: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:write")),
):
    _require_v2_enabled()
    from app.routers.user import rotate_user_subscription_link

    dbuser = _get_owned_user(db, admin, username)
    return rotate_user_subscription_link(db=db, dbuser=dbuser, admin=admin)


@router.post("/users/{username}/revoke-sub", response_model=UserResponse)
def revoke_sub(
    username: str,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:write")),
):
    _require_v2_enabled()
    from app.routers.user import revoke_user_subscription

    dbuser = _get_owned_user(db, admin, username)
    return revoke_user_subscription(bg=bg, db=db, dbuser=dbuser, admin=admin)


@router.post("/users/{username}/apply-plan", response_model=UserResponse)
def apply_plan(
    username: str,
    body: ApplyPlanBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:write")),
):
    _require_v2_enabled()
    from app.routers.user import ApplyPlanBody as DashApplyPlanBody
    from app.routers.user import apply_plan_to_user_endpoint

    dbuser = _get_owned_user(db, admin, username)
    return apply_plan_to_user_endpoint(
        body=DashApplyPlanBody(plan_id=body.plan_id),
        db=db,
        dbuser=dbuser,
        admin=admin,
    )


@router.get("/users/{username}/usage", response_model=UsageV2)
def user_usage(
    username: str,
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:read")),
):
    _require_v2_enabled()
    from app.dependencies import validate_dates

    dbuser = _get_owned_user(db, admin, username)
    start_dt, end_dt = validate_dates(start, end)
    usages = crud.get_user_usages(db, dbuser, start_dt, end_dt)
    return UsageV2(username=dbuser.username, usages=usages)


# ---------------------------------------------------------------------------
# Templates (read-only for bots / resellers)
# ---------------------------------------------------------------------------


@router.get("/templates", response_model=List[TemplateV2])
def list_templates(
    offset: Optional[int] = None,
    limit: Optional[int] = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("templates:read")),
):
    _require_v2_enabled()
    rows = crud.get_user_templates(db, offset=offset, limit=limit)
    return [
        TemplateV2(
            id=t.id,
            name=t.name,
            data_limit=t.data_limit,
            expire_duration=t.expire_duration,
            username_prefix=t.username_prefix,
            username_suffix=t.username_suffix,
        )
        for t in rows
    ]


@router.get("/templates/{template_id}", response_model=UserTemplateResponse)
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("templates:read")),
):
    _require_v2_enabled()
    tpl = crud.get_user_template(db, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


# ---------------------------------------------------------------------------
# Plans (reseller catalog)
# ---------------------------------------------------------------------------


@router.get("/plans", response_model=List[PlanV2])
def list_plans(
    enabled_only: bool = False,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("plans:read")),
):
    _require_v2_enabled()
    from app.tenant.plan_ops import get_scoped_plans

    return get_scoped_plans(db, admin, enabled_only=enabled_only)


@router.post("/plans", response_model=PlanV2)
def create_plan(
    body: PlanCreateBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("plans:write")),
):
    _require_v2_enabled()
    from app.tenant.plan_ops import plan_name_taken, reseller_plan_scope

    tenant_id, owner_admin_id = reseller_plan_scope(db, admin)
    if plan_name_taken(db, body.name, tenant_id=tenant_id, owner_admin_id=owner_admin_id):
        raise HTTPException(status_code=409, detail="Plan name already exists in your catalog")
    return crud.create_plan(
        db,
        tenant_id=tenant_id,
        owner_admin_id=owner_admin_id,
        **body.model_dump(),
    )


@router.put("/plans/{plan_id}", response_model=PlanV2)
def modify_plan(
    plan_id: int,
    body: PlanModifyBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("plans:write")),
):
    _require_v2_enabled()
    from app.tenant.plan_ops import assert_plan_accessible, plan_name_taken, reseller_plan_scope

    plan = crud.get_plan_by_id(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    assert_plan_accessible(db, admin, plan)
    tenant_id, owner_admin_id = reseller_plan_scope(db, admin)
    new_name = body.name if body.name is not None else plan.name
    if new_name != plan.name and plan_name_taken(
        db, new_name, tenant_id=tenant_id, owner_admin_id=owner_admin_id, exclude_id=plan.id
    ):
        raise HTTPException(status_code=409, detail="Plan name already exists in your catalog")
    return crud.update_plan(db, plan, **body.model_dump(exclude_unset=True))


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("plans:write")),
):
    _require_v2_enabled()
    from app.tenant.plan_ops import assert_plan_accessible

    plan = crud.get_plan_by_id(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    assert_plan_accessible(db, admin, plan)
    try:
        crud.remove_plan(db, plan)
    except crud.PlanInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"detail": "Plan removed"}


# ---------------------------------------------------------------------------
# Billing + reseller workspace
# ---------------------------------------------------------------------------


@router.get("/wallet", response_model=WalletV2)
def get_wallet(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("billing:read")),
):
    _require_v2_enabled()
    _require_billing_enabled()
    from app import billing

    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        if admin.is_sudo:
            return WalletV2(admin_id=0, balance=0)
        raise HTTPException(
            status_code=400,
            detail="Billing requires a database-backed admin",
        )
    return billing.get_or_create_wallet(db, dbadmin.id)


@router.get("/transactions", response_model=Page[TransactionV2])
def list_transactions(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("billing:read")),
):
    _require_v2_enabled()
    _require_billing_enabled()
    from app import billing
    from app.db.models import Transaction

    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        return Page[TransactionV2](items=[], total=0, page=page, size=size)

    query = (
        db.query(Transaction)
        .filter(Transaction.admin_id == dbadmin.id)
        .order_by(Transaction.id.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * size).limit(size).all()
    # Prefer billing helper for consistency when available for first page size.
    _ = billing  # keep import intentional for billing package side-effects
    return Page[TransactionV2](
        items=[
            TransactionV2(
                id=t.id,
                admin_id=t.admin_id,
                amount=t.amount,
                type=t.type,
                description=t.description,
                reference=t.reference,
                created_at=t.created_at,
            )
            for t in rows
        ],
        total=total,
        page=page,
        size=size,
    )


@router.get("/workspace", response_model=WorkspaceV2)
def get_workspace(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("reseller:read")),
):
    _require_v2_enabled()
    from app.tenant.reseller_ops import workspace_summary

    summary: Dict[str, Any] = workspace_summary(db, admin)
    return WorkspaceV2(
        username=summary.get("username") or admin.username,
        role=summary.get("role") or "",
        tenant_id=summary.get("tenant_id"),
        tenant_name=summary.get("tenant_name"),
        tenant_slug=summary.get("tenant_slug"),
        users_count=int(summary.get("users_count") or 0),
        max_users=summary.get("max_users"),
        nodes_count=int(summary.get("nodes_count") or 0),
        max_nodes=summary.get("max_nodes"),
        wallet_balance=summary.get("wallet_balance"),
        wallet_low=bool(summary.get("wallet_low")),
        wallet_blocked=bool(summary.get("wallet_blocked")),
        users_usage=int(summary.get("users_usage") or 0),
        max_total_traffic=summary.get("max_total_traffic"),
        traffic_remaining=summary.get("traffic_remaining"),
        prepaid_traffic_remaining=int(summary.get("prepaid_traffic_remaining") or 0),
        currency_label=summary.get("currency_label"),
    )


# ---------------------------------------------------------------------------
# White-label branding (reseller bot)
# ---------------------------------------------------------------------------


def _require_white_label_enabled():
    if not feature_flags.is_enabled("white_label"):
        raise HTTPException(status_code=404, detail="White-label branding is disabled")


@router.get("/branding", response_model=BrandingResponse)
def get_branding(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("branding:read")),
):
    """Read the caller's tenant branding (name, logo, domain, sub path/port)."""
    _require_v2_enabled()
    _require_white_label_enabled()
    from app.routers.tenant import my_branding

    return my_branding(db=db, admin=admin)


@router.put("/branding", response_model=BrandingResponse)
def update_branding(
    body: BrandingUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("branding:write")),
):
    """Update the caller's white-label brand (panel title, logo, domain, …)."""
    _require_v2_enabled()
    _require_white_label_enabled()
    from app.routers.tenant import update_my_branding

    return update_my_branding(body=body, db=db, admin=admin)


@router.get("/branding/subscription-ports")
def branding_subscription_ports(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("branding:read")),
):
    _require_v2_enabled()
    from app.routers.tenant import branding_subscription_ports as dash_ports

    return dash_ports(db=db, admin=admin)


@router.get("/branding/subscription-ssl")
def branding_subscription_ssl(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("branding:read")),
):
    """DNS + Let's Encrypt status for the reseller branding domain."""
    _require_v2_enabled()
    from app.routers.tenant import my_branding_subscription_ssl

    return my_branding_subscription_ssl(db=db, admin=admin)


@router.post("/branding/subscription-ssl")
def enable_branding_subscription_ssl(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("branding:write")),
):
    """Issue / retry Let's Encrypt for the saved branding domain."""
    _require_v2_enabled()
    from app.routers.tenant import enable_my_branding_subscription_ssl

    return enable_my_branding_subscription_ssl(db=db, admin=admin)
