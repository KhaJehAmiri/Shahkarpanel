"""Admin management of the dedicated-IP pool for Trader accounts (phase B)."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import dedicated_ip as svc
from app import feature_flags
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["DedicatedIP"],
    prefix="/api/dedicated-ip",
    responses={401: responses._401, 403: responses._403, 404: responses._404},
)


def _require_client_api() -> None:
    if not feature_flags.is_enabled("client_api"):
        raise HTTPException(status_code=404, detail="Client API is disabled")


class IPItem(BaseModel):
    id: int
    address: str
    node_id: Optional[int] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    assigned_at: Optional[datetime] = None


class PoolResponse(BaseModel):
    total: int
    assigned: int
    free: int
    items: List[IPItem]


class AddIPBody(BaseModel):
    address: str
    node_id: Optional[int] = None


class AssignBody(BaseModel):
    username: str


def _item(db: Session, ip) -> IPItem:
    username = None
    if ip.user_id:
        u = crud.get_user_by_id(db, ip.user_id)
        username = u.username if u else None
    return IPItem(
        id=ip.id,
        address=ip.address,
        node_id=ip.node_id,
        user_id=ip.user_id,
        username=username,
        assigned_at=ip.assigned_at,
    )


@router.get("", response_model=PoolResponse)
def list_pool(
    only_free: bool = False,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_client_api()
    stats = svc.pool_stats(db)
    items = [_item(db, ip) for ip in svc.list_pool(db, only_free=only_free)]
    return PoolResponse(items=items, **stats)


@router.post("", response_model=IPItem, status_code=201)
def add_ip(
    body: AddIPBody,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_client_api()
    ip = svc.add_to_pool(db, body.address.strip(), node_id=body.node_id)
    return _item(db, ip)


@router.post("/assign", response_model=IPItem)
def assign(
    body: AssignBody,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_client_api()
    user = crud.get_user(db, body.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ip = svc.assign_to_user(db, user.id)
    if not ip:
        raise HTTPException(status_code=409, detail="Dedicated IP pool is empty")
    return _item(db, ip)


@router.post("/release", status_code=204)
def release(
    body: AssignBody,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_client_api()
    user = crud.get_user(db, body.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    svc.release(db, user.id)
