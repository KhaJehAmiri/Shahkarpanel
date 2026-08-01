"""Reseller workspace API — KPIs, quotas, sub-resellers, onboarding."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.rbac import require_permission
from app.tenant.reseller_ops import workspace_summary
from app.tenant.sub_reseller import (
    complete_onboarding,
    create_sub_reseller,
    db_admin,
    list_children,
    onboarding_status,
    update_sub_reseller,
)
from app.utils import responses

router = APIRouter(
    tags=["Reseller"],
    prefix="/api/reseller",
    responses={401: responses._401, 403: responses._403},
)


class WorkspaceResponse(BaseModel):
    username: str
    role: str
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    tenant_slug: Optional[str] = None
    byo_node_discount_percent: int = 0
    users_count: int = 0
    max_users: Optional[int] = None
    nodes_count: int = 0
    max_nodes: Optional[int] = None
    wallet_balance: Optional[int] = None
    wallet_low: bool = False
    wallet_blocked: bool = False
    usage_rate_per_gb: int = 0
    users_usage: int = 0
    max_total_traffic: Optional[int] = None
    traffic_remaining: Optional[int] = None
    prepaid_traffic_remaining: int = 0
    pending_usage_cost: int = 0
    pending_usage_bytes: int = 0
    capped_users: int = 0
    currency_label: Optional[str] = None
    last_usage_debit: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(from_attributes=True)


class SubAccountResponse(BaseModel):
    username: str
    role: Optional[str] = None
    max_users: Optional[int] = None
    max_nodes: Optional[int] = None
    parent_admin_id: Optional[int] = None
    commission_percent: int = 0
    model_config = ConfigDict(from_attributes=True)


class SubAccountCreate(BaseModel):
    username: str
    password: str
    max_users: Optional[int] = None
    max_nodes: Optional[int] = None
    commission_percent: Optional[int] = None


class SubAccountUpdate(BaseModel):
    max_users: Optional[int] = None
    max_nodes: Optional[int] = None
    commission_percent: Optional[int] = None
    password: Optional[str] = None


class OnboardingStatusResponse(BaseModel):
    show_wizard: bool
    completed: bool
    steps: Dict[str, bool]


@router.get("/workspace", response_model=WorkspaceResponse)
def get_workspace(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("system:read")),
) -> Dict[str, Any]:
    """Reseller dashboard KPIs: quotas, wallet, tenant context."""
    return workspace_summary(db, admin)


@router.get("/sub-accounts", response_model=List[SubAccountResponse])
def list_sub_accounts(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("system:read")),
):
    """List sub-resellers owned by the current admin."""
    parent = db_admin(db, admin)
    if parent is None:
        raise HTTPException(status_code=400, detail="Admin not found")
    if admin.is_sudo:
        return []
    return list_children(db, parent.id)


@router.post("/sub-accounts", response_model=SubAccountResponse)
def add_sub_account(
    body: SubAccountCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Create a sub-reseller under the current account."""
    if admin.is_sudo:
        raise HTTPException(status_code=400, detail="Use /api/admin for sudo-created accounts")
    parent = db_admin(db, admin)
    if parent is None:
        raise HTTPException(status_code=400, detail="Admin not found")
    child = create_sub_reseller(
        db,
        parent,
        username=body.username.strip(),
        password=body.password,
        max_users=body.max_users,
        max_nodes=body.max_nodes,
        commission_percent=body.commission_percent,
    )
    return child


@router.patch("/sub-accounts/{username}", response_model=SubAccountResponse)
def patch_sub_account(
    username: str,
    body: SubAccountUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Update quotas or commission on a sub-reseller."""
    if admin.is_sudo:
        raise HTTPException(status_code=400, detail="Use /api/admin for sudo-managed accounts")
    parent = db_admin(db, admin)
    if parent is None:
        raise HTTPException(status_code=400, detail="Admin not found")
    child = crud.get_admin(db, username)
    if child is None:
        raise HTTPException(status_code=404, detail="Sub-reseller not found")
    return update_sub_reseller(
        db,
        parent,
        child,
        max_users=body.max_users if "max_users" in body.model_fields_set else ...,
        max_nodes=body.max_nodes if "max_nodes" in body.model_fields_set else ...,
        commission_percent=body.commission_percent,
        password=body.password,
    )


@router.get("/onboarding", response_model=OnboardingStatusResponse)
def get_onboarding(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("system:read")),
):
    """Reseller first-run wizard progress."""
    return onboarding_status(db, admin)


@router.post("/onboarding/complete", response_model=OnboardingStatusResponse)
def finish_onboarding(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("system:read")),
):
    """Mark reseller onboarding as done."""
    complete_onboarding(db, admin)
    return onboarding_status(db, admin)
