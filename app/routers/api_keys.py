from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app import api_keys
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["API Keys"],
    prefix="/api/api-keys",
    responses={401: responses._401, 403: responses._403},
)


class ApiKeyCreate(BaseModel):
    name: str
    scopes: Optional[List[str]] = None


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: Optional[List[str]] = None
    revoked: bool
    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreated(ApiKeyResponse):
    key: str


def _admin_id(db: Session, admin: Admin) -> int:
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        raise HTTPException(
            status_code=400,
            detail="Admin record not found in database — run migrations or recreate the admin user",
        )
    return dbadmin.id


@router.get("", response_model=List[ApiKeyResponse])
def list_api_keys(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    from app.db.models import ApiKey

    return (
        db.query(ApiKey)
        .filter(ApiKey.admin_id == _admin_id(db, admin))
        .order_by(ApiKey.id.desc())
        .all()
    )


@router.post("", response_model=ApiKeyCreated)
def create_api_key(
    body: ApiKeyCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Create a new API key. The raw key is returned once and never again."""
    record, raw = api_keys.create_api_key(
        db, _admin_id(db, admin), body.name, scopes=body.scopes
    )
    return ApiKeyCreated(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        scopes=record.scopes,
        revoked=record.revoked,
        key=raw,
    )


@router.delete("/{key_id}")
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    from app.db.models import ApiKey

    record = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.admin_id == _admin_id(db, admin))
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found")
    record.revoked = True
    db.commit()
    return {"detail": "API key revoked"}
