"""Portal username format + availability checks (buy-new-account flow)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db import crud
from app.models.user import USERNAME_REGEXP

USERNAME_FORMAT_DETAIL = (
    "Username only can be 3 to 32 characters and contain a-z, A-Z, 0-9, and underscores."
)
USERNAME_TAKEN_DETAIL = "Username already exists"


def normalize_username(username: Optional[str]) -> str:
    return (username or "").strip().lower()


def username_format_ok(username: str) -> bool:
    return bool(username) and bool(USERNAME_REGEXP.match(username))


def check_portal_username(db: Session, username: Optional[str]) -> Dict[str, Any]:
    """Return validation result for live portal feedback and API guards.

    ``reason`` values: ``too_short``, ``too_long``, ``invalid_format``, ``taken``, or null.
    """
    u = normalize_username(username)
    if len(u) < 3:
        return {
            "username": u,
            "valid": False,
            "available": False,
            "reason": "too_short",
            "detail": USERNAME_FORMAT_DETAIL,
        }
    if len(u) > 32 or not username_format_ok(u):
        return {
            "username": u,
            "valid": False,
            "available": False,
            "reason": "invalid_format",
            "detail": USERNAME_FORMAT_DETAIL,
        }
    if crud.get_user(db, u) is not None or crud.get_admin(db, u) is not None:
        return {
            "username": u,
            "valid": True,
            "available": False,
            "reason": "taken",
            "detail": USERNAME_TAKEN_DETAIL,
        }
    return {
        "username": u,
        "valid": True,
        "available": True,
        "reason": None,
        "detail": None,
    }


def require_available_portal_username(db: Session, username: Optional[str]) -> str:
    """Normalize and raise HTTP-friendly errors if unusable. Returns clean username."""
    from fastapi import HTTPException

    result = check_portal_username(db, username)
    if not result["valid"]:
        raise HTTPException(status_code=400, detail=result["detail"] or USERNAME_FORMAT_DETAIL)
    if not result["available"]:
        raise HTTPException(status_code=409, detail=result["detail"] or USERNAME_TAKEN_DETAIL)
    return result["username"]
