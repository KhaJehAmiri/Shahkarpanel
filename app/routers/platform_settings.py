"""Platform commercial settings — fully UI-managed (phase 6)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import feature_flags, platform_settings as ps
from app.db import Session, get_db
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["PlatformSettings"],
    prefix="/api/platform-settings",
    responses={401: responses._401, 403: responses._403},
)


class SettingItem(BaseModel):
    key: str
    value: Any
    type: str
    has_secret: bool = False
    is_set: bool = False


class SettingsUpdate(BaseModel):
    settings: Dict[str, Any]


@router.get("", response_model=List[SettingItem])
def list_settings(_: Admin = Depends(Admin.check_sudo_admin)):
    if not feature_flags.is_enabled("billing"):
        raise HTTPException(status_code=404, detail="Billing is disabled")
    return ps.list_settings_for_ui()


@router.put("", response_model=List[SettingItem])
def update_settings(
    body: SettingsUpdate,
    _: Admin = Depends(Admin.check_sudo_admin),
):
    if not feature_flags.is_enabled("billing"):
        raise HTTPException(status_code=404, detail="Billing is disabled")
    try:
        ps.update_settings_bulk(body.settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ps.list_settings_for_ui()

