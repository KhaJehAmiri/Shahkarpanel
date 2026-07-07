"""Role-based access control.

Additive layer on top of the existing ``is_sudo`` flag. Sudo admins implicitly
have every permission; other admins get permissions from their role. Use
:func:`require_permission` as a FastAPI dependency to guard endpoints.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Set

from fastapi import Depends, HTTPException, status

RBAC_OVERRIDES_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "rbac_overrides.json")
)

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
    # Granular infra permissions so non-sudo roles can get partial (usually
    # read-only) access to core config, hosts and backups instead of the
    # all-or-nothing sudo gate.
    "core:read",
    "core:write",
    "hosts:read",
    "hosts:write",
    "backup:read",
    "backup:write",
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
        "billing:write",
        "system:read",
        "hosts:read",
        "hosts:write",
    },
    "support": {
        "users:read",
        "nodes:read",
        "system:read",
        "hosts:read",
    },
    # Read-only auditor: sees infra state but changes nothing.
    "auditor": {
        "users:read",
        "nodes:read",
        "system:read",
        "core:read",
        "hosts:read",
        "backup:read",
        "billing:read",
    },
}


def _load_overrides() -> Dict[str, Set[str]]:
    if not os.path.isfile(RBAC_OVERRIDES_PATH):
        return {}
    try:
        with open(RBAC_OVERRIDES_PATH, "r") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    out: Dict[str, Set[str]] = {}
    if isinstance(raw, dict):
        for role, perms in raw.items():
            if isinstance(perms, list):
                out[str(role)] = {str(p) for p in perms if p in PERMISSIONS}
    return out


def get_role_matrix() -> Dict[str, list]:
    merged = {role: sorted(perms) for role, perms in ROLE_PERMISSIONS.items()}
    for role, perms in _load_overrides().items():
        merged[role] = sorted(perms)
    return merged


def save_role_permissions(role: str, permissions: list[str]) -> None:
    if role == "sudo":
        raise ValueError("sudo role cannot be customized")
    cleaned = [p for p in permissions if p in PERMISSIONS]
    overrides = _load_overrides()
    overrides[role] = set(cleaned)
    os.makedirs(os.path.dirname(RBAC_OVERRIDES_PATH), mode=0o700, exist_ok=True)
    serializable = {k: sorted(v) for k, v in overrides.items()}
    with open(RBAC_OVERRIDES_PATH, "w") as f:
        json.dump(serializable, f, indent=2)


def role_permissions(role: str) -> Set[str]:
    if role == "sudo":
        return set(PERMISSIONS)
    overrides = _load_overrides()
    if role in overrides:
        return overrides[role]
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
