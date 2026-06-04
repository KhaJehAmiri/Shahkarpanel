"""API key issuance and authentication for the v2 developer platform.

Only a SHA-256 hash of each key is stored; the raw key is shown once at
creation. Keys carry optional scopes for fine-grained access.
"""
import hashlib
import secrets
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import Depends, HTTPException, Request, status

from app.db import Session, get_db
from app.db.models import ApiKey


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_key() -> Tuple[str, str, str]:
    """Return (raw_key, prefix, key_hash)."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    raw = f"nxp_{prefix}_{secret}"
    return raw, prefix, _hash(raw)


def create_api_key(
    db: Session, admin_id: int, name: str, scopes: Optional[list] = None
) -> Tuple[ApiKey, str]:
    raw, prefix, key_hash = generate_key()
    record = ApiKey(
        admin_id=admin_id, name=name, prefix=prefix, key_hash=key_hash, scopes=scopes
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, raw


def authenticate_api_key(db: Session, raw: str) -> Optional[ApiKey]:
    record = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == _hash(raw), ApiKey.revoked.is_(False))
        .first()
    )
    if record is None:
        return None
    record.last_used_at = datetime.utcnow()
    db.commit()
    return record


def _scopes_allow(record: Optional[ApiKey], required: str) -> bool:
    if record is None:
        return True
    scopes: List[str] = list(record.scopes or [])
    if not scopes:
        return False
    if "*" in scopes or required in scopes:
        return True
    prefix = required.split(":", 1)[0] + ":*"
    return prefix in scopes


def get_v2_admin(request: Request, db: Session = Depends(get_db)):
    """Authenticate a v2 request via X-API-Key or a bearer admin token."""
    from app.db.models import Admin as DBAdmin
    from app.models.admin import Admin

    request.state.api_key_record = None

    api_key = request.headers.get("X-API-Key")
    if api_key:
        record = authenticate_api_key(db, api_key)
        if record is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        request.state.api_key_record = record
        dbadmin = db.query(DBAdmin).filter(DBAdmin.id == record.admin_id).first()
        if dbadmin is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner not found")
        return Admin.model_validate(dbadmin)

    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    admin = Admin.get_admin(token, db) if token else None
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Provide an X-API-Key or a bearer token",
        )
    return admin


def require_v2_scope(scope: str):
    """Enforce API-key scopes on v2 routes (bearer admin tokens bypass scope checks)."""

    def dependency(
        request: Request,
        admin=Depends(get_v2_admin),
    ):
        record: Optional[ApiKey] = getattr(request.state, "api_key_record", None)
        if record is not None and not _scopes_allow(record, scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key missing scope: {scope}",
            )
        return admin

    return dependency
