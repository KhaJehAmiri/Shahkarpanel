"""Subscription issuance guards — central quota/status checks for config export."""

from fastapi import HTTPException

from app.models.user import UserResponse, UserStatus


def ensure_subscription_config_allowed(user: UserResponse) -> None:
    """Block proxy config export for inactive or over-quota users.

    Aligns Xray subscription paths with WireGuard .conf gating so a disabled
    or limited account cannot keep using configs after admin action.
    """
    if user.status not in (UserStatus.active, UserStatus.on_hold):
        raise HTTPException(status_code=403, detail="Subscription is not active")
    if user.data_limit and user.used_traffic >= user.data_limit:
        raise HTTPException(status_code=403, detail="Data limit reached")
