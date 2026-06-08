from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.rbac import require_permission
from app.tenant.plan_ops import (
    assert_plan_accessible,
    get_scoped_plans,
    plan_name_taken,
    reseller_plan_scope,
)
from app.utils import responses

router = APIRouter(
    tags=["Plans"],
    prefix="/api/plans",
    responses={401: responses._401, 403: responses._403},
)


class PlanCreate(BaseModel):
    name: str
    price: int = 0
    data_limit: Optional[int] = None
    duration_days: Optional[int] = None
    device_limit: Optional[int] = None
    enabled: bool = True


class PlanModify(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    data_limit: Optional[int] = None
    duration_days: Optional[int] = None
    device_limit: Optional[int] = None
    enabled: Optional[bool] = None


class PlanResponse(BaseModel):
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


@router.get("", response_model=List[PlanResponse])
def list_plans(
    enabled_only: bool = False,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:read")),
):
    return get_scoped_plans(db, admin, enabled_only=enabled_only)


@router.post("", response_model=PlanResponse)
def create_plan(
    body: PlanCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:write")),
):
    tenant_id, owner_admin_id = reseller_plan_scope(db, admin)
    if plan_name_taken(db, body.name, tenant_id=tenant_id, owner_admin_id=owner_admin_id):
        raise HTTPException(status_code=409, detail="Plan name already exists in your catalog")
    return crud.create_plan(
        db,
        tenant_id=tenant_id,
        owner_admin_id=owner_admin_id,
        **body.model_dump(),
    )


@router.put("/{plan_id}", response_model=PlanResponse)
def modify_plan(
    plan_id: int,
    body: PlanModify,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:write")),
):
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


@router.delete("/{plan_id}")
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("billing:write")),
):
    plan = crud.get_plan_by_id(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    assert_plan_accessible(db, admin, plan)
    crud.remove_plan(db, plan)
    return {"detail": "Plan removed"}
