"""Role-based access control.

Additive layer on top of the existing ``is_sudo`` flag. Sudo admins implicitly
have every permission; other admins get permissions from their role. Use
:func:`require_permission` as a FastAPI dependency to guard endpoints.
"""
from typing import Dict, Set

from fastapi import Depends, HTTPException, status

# Permission catalogue (resource:action).
PERMISSIONS = {
    "users:read",
    "users:write",
    "nodes:read",
    "nodes:write",
    "nodes:provision",
    "billing:read",
    "billing:write",
    "system:read",
    "admins:write",
}

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    # 'sudo' is handled implicitly (all permissions).
    "reseller": {
        "users:read",
        "users:write",
        "nodes:read",
        # A reseller may bring their own nodes (phase 6) but not touch the
        # owner's shared nodes (that's nodes:write).
        "nodes:provision",
        "billing:read",
        "system:read",
    },
    "support": {
        "users:read",
        "nodes:read",
        "system:read",
    },
}


def role_permissions(role: str) -> Set[str]:
    if role == "sudo":
        return set(PERMISSIONS)
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(admin, permission: str) -> bool:
    if getattr(admin, "is_sudo", False):
        return True
    return permission in role_permissions(getattr(admin, "role", None) or "reseller")


def require_permission(permission: str):
    """FastAPI dependency factory enforcing a single permission."""
    from app.models.admin import Admin

    def dependency(admin: "Admin" = Depends(Admin.get_current)) -> "Admin":
        if not has_permission(admin, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return admin

    return dependency
