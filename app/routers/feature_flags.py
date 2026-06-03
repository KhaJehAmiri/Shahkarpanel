from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import feature_flags
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["Feature Flags"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)


class FeatureFlagInfo(BaseModel):
    name: str
    enabled: bool
    default: bool
    description: str


class FeatureFlagModify(BaseModel):
    enabled: bool


def _info(name: str) -> FeatureFlagInfo:
    spec = feature_flags.KNOWN_FLAGS[name]
    return FeatureFlagInfo(
        name=name,
        enabled=feature_flags.is_enabled(name),
        default=spec.default,
        description=spec.description,
    )


@router.get("/feature-flags", response_model=List[FeatureFlagInfo])
def list_feature_flags(_: Admin = Depends(Admin.check_sudo_admin)):
    """List all known feature flags and their resolved global state."""
    return [_info(name) for name in feature_flags.KNOWN_FLAGS]


@router.put("/feature-flags/{name}", response_model=FeatureFlagInfo)
def set_feature_flag(
    name: str,
    body: FeatureFlagModify,
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Set the global value of a feature flag. Accessible only to sudo admins."""
    if name not in feature_flags.KNOWN_FLAGS:
        raise HTTPException(status_code=404, detail="Unknown feature flag")
    feature_flags.set_flag(name, body.enabled)
    return _info(name)
