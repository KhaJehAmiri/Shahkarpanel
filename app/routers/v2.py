"""Versioned, paginated v2 API for the developer platform.

Authenticated via an API key (``X-API-Key``) or a bearer admin token. Gated by
the ``api_v2`` feature flag. Non-sudo admins only see their own users.
"""
from typing import Generic, List, Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app import feature_flags
from app.api_keys import require_v2_scope
from app.db import Session, crud, get_db
from app.models.admin import Admin
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
    username: str
    status: str
    used_traffic: int
    data_limit: Optional[int] = None
    expire: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


def _require_v2_enabled():
    if not feature_flags.is_enabled("api_v2"):
        raise HTTPException(status_code=404, detail="v2 API is disabled")


@router.get("/users", response_model=Page[UserV2])
def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_v2_scope("users:read")),
):
    _require_v2_enabled()
    from app.db.models import User

    query = db.query(User)
    if not admin.is_sudo:
        dbadmin = crud.get_admin(db, admin.username)
        query = query.filter(User.admin_id == (dbadmin.id if dbadmin else -1))

    total = query.count()
    rows = query.order_by(User.id).offset((page - 1) * size).limit(size).all()
    items = [
        UserV2(
            username=u.username,
            status=u.status.value if hasattr(u.status, "value") else str(u.status),
            used_traffic=u.used_traffic or 0,
            data_limit=u.data_limit,
            expire=u.expire,
        )
        for u in rows
    ]
    return Page[UserV2](items=items, total=total, page=page, size=size)
