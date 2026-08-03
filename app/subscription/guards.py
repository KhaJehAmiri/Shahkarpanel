"""Subscription issuance guards — central quota/status checks for config export."""

from datetime import datetime
from typing import Literal, Optional, TypedDict

from fastapi import HTTPException

from app.models.user import UserResponse, UserStatus

BlockReason = Literal["inactive", "data_limit", "expired", "family_schedule"]


class SubscriptionAccess(TypedDict):
    config_available: bool
    block_reason: Optional[BlockReason]


def _family_schedule_blocks(user: UserResponse) -> bool:
    controls = getattr(user, "family_controls", None)
    if not isinstance(controls, dict):
        return False
    from app.family_guard.schedule import evaluate_access

    # Prefer live evaluation so pause/windows apply immediately without waiting for the job.
    allowed, _reason = evaluate_access(controls)
    return not allowed


def subscription_access(user: UserResponse) -> SubscriptionAccess:
    """Read-only access metadata for the subscription UI (always allowed)."""
    now_ts = datetime.utcnow().timestamp()
    if user.status == UserStatus.expired:
        return {"config_available": False, "block_reason": "expired"}
    if user.status in (UserStatus.disabled,):
        return {"config_available": False, "block_reason": "inactive"}
    if user.expire and user.expire > 0 and user.expire <= now_ts:
        return {"config_available": False, "block_reason": "expired"}
    if user.status == UserStatus.limited:
        return {"config_available": False, "block_reason": "data_limit"}
    if user.status not in (UserStatus.active, UserStatus.on_hold):
        return {"config_available": False, "block_reason": "inactive"}
    if user.data_limit and user.used_traffic >= user.data_limit:
        return {"config_available": False, "block_reason": "data_limit"}
    if _family_schedule_blocks(user):
        return {"config_available": False, "block_reason": "family_schedule"}
    return {"config_available": True, "block_reason": None}


def ensure_subscription_config_allowed(user: UserResponse) -> None:
    """Block proxy config export for inactive or over-quota users.

    Aligns Xray subscription paths with WireGuard .conf gating so a disabled
    or limited account cannot keep using configs after admin action.
    The HTML subscription page and ``/info`` stay available so users see
    usage/status instead of a bare 403.
    """
    access = subscription_access(user)
    if access["config_available"]:
        return
    if access["block_reason"] == "data_limit":
        raise HTTPException(status_code=403, detail="Data limit reached")
    if access["block_reason"] == "family_schedule":
        raise HTTPException(
            status_code=403,
            detail="Family Guard: outside allowed hours or daily limit reached",
        )
    raise HTTPException(status_code=403, detail="Subscription is not active")
