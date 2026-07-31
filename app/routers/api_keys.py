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
    """Resolve (or create) the DB admin row that owns API keys.

    Env-only sudo (``SUDO_USERNAME`` / ``SUDOERS``) can log in without an
    ``admins`` row. API keys need ``admin_id``, so we materialize a sudo row
    on first use. Password is a random unused hash — login stays via env.
    """
    dbadmin = crud.ensure_db_admin(db, admin.username, is_sudo=admin.is_sudo)
    if dbadmin is None:
        raise HTTPException(
            status_code=400,
            detail="Admin record not found in database — run migrations or recreate the admin user",
        )
    return dbadmin.id


@router.get("/scopes", response_model=List[str])
def list_allowed_scopes(
    admin: Admin = Depends(Admin.get_current),
):
    """Scopes the current admin may attach to a new API key."""
    return api_keys.allowed_scopes_for_admin(admin)


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
    admin: Admin = Depends(Admin.get_current),
):
    """Create a new API key for the current admin (sudo or reseller).

    The raw key is returned once and never again. Scopes are clamped to the
    caller's role; omitted scopes default to every scope that role may hold.
    """
    scopes = api_keys.clamp_scopes_for_admin(admin, body.scopes)
    record, raw = api_keys.create_api_key(
        db, _admin_id(db, admin), body.name, scopes=scopes
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
