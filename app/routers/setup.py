"""First-run setup wizard (phase 6).

Lets the first sudo admin finish configuration from the UI instead of editing
``.env`` by hand: public address, default brand, and which phase-6 features to
turn on. Completion is tracked with the ``setup_completed`` flag.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import feature_flags, tenant as tenant_svc
from app.db import Session, get_db
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["Setup"],
    prefix="/api/setup",
    responses={401: responses._401, 403: responses._403},
)

_COMPLETED_FLAG = "setup_completed"
# Flags the wizard is allowed to toggle.
_TOGGLEABLE = {
    "tenants", "white_label", "node_provisioning", "tunneling",
    "billing", "smart_routing",
}


class SetupStatus(BaseModel):
    completed: bool
    show_wizard: bool


class SetupRequest(BaseModel):
    panel_title: Optional[str] = None
    primary_color: Optional[str] = None
    support_url: Optional[str] = None
    logo_url: Optional[str] = None
    enable_features: List[str] = []


@router.get("/status", response_model=SetupStatus)
def setup_status():
    """Public: the dashboard checks this on load to decide whether to show the wizard."""
    completed = feature_flags.is_enabled(_COMPLETED_FLAG)
    show = feature_flags.is_enabled("setup_wizard") and not completed
    return SetupStatus(completed=completed, show_wizard=show)


@router.post("/", response_model=SetupStatus)
def run_setup(
    body: SetupRequest,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Apply first-run configuration. Sudo only."""
    if feature_flags.is_enabled(_COMPLETED_FLAG):
        raise HTTPException(status_code=409, detail="Setup already completed")

    branding_fields = {
        k: v for k, v in {
            "panel_title": body.panel_title,
            "primary_color": body.primary_color,
            "support_url": body.support_url,
            "logo_url": body.logo_url,
        }.items() if v is not None
    }
    if branding_fields:
        tenant_svc.set_branding(db, None, **branding_fields)

    for name in body.enable_features:
        if name not in _TOGGLEABLE:
            raise HTTPException(status_code=422, detail=f"Feature not toggleable: {name}")
        feature_flags.set_flag(name, True)

    feature_flags.set_flag(_COMPLETED_FLAG, True)
    return SetupStatus(completed=True, show_wizard=False)
