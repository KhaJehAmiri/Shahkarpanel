"""Sub-reseller hierarchy helpers (phase 5)."""
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import Admin, Plan, User
from app.models.admin import Admin as AdminModel
from app.models.admin import AdminCreate
from app import platform_settings as ps


def db_admin(db: Session, admin) -> Optional[Admin]:
    return crud.get_admin(db, admin.username)


def list_children(db: Session, parent_id: int) -> List[Admin]:
    return (
        db.query(Admin)
        .filter(Admin.parent_admin_id == parent_id, Admin.is_sudo.is_(False))
        .order_by(Admin.id)
        .all()
    )


def count_children(db: Session, parent_id: int) -> int:
    return db.query(Admin).filter(Admin.parent_admin_id == parent_id).count()


def assert_can_create_child(db: Session, parent: Admin) -> None:
    if parent.is_sudo:
        return
    current = count_children(db, parent.id)
    limit = ps.get_int("reseller.sub_reseller_max", 10)
    if current >= limit:
        raise HTTPException(
            status_code=400,
            detail=f"Sub-reseller limit reached ({current}/{limit})",
        )


def clamp_child_quota(parent_value: Optional[int], child_value: Optional[int]) -> Optional[int]:
    if parent_value is None:
        return child_value
    if child_value is None:
        return parent_value
    return min(parent_value, child_value)


def create_sub_reseller(
    db: Session,
    parent: Admin,
    *,
    username: str,
    password: str,
    max_users: Optional[int] = None,
    max_nodes: Optional[int] = None,
    commission_percent: Optional[int] = None,
) -> Admin:
    assert_can_create_child(db, parent)
    if crud.get_admin(db, username):
        raise HTTPException(status_code=409, detail="Admin already exists")

    body = AdminCreate(
        username=username,
        password=password,
        is_sudo=False,
        role="reseller",
        max_users=clamp_child_quota(parent.max_users, max_users),
        max_nodes=clamp_child_quota(parent.max_nodes, max_nodes),
    )
    child = crud.create_admin(db, body)
    child.parent_admin_id = parent.id
    child.tenant_id = parent.tenant_id
    if commission_percent is not None:
        child.commission_percent = max(0, min(100, int(commission_percent)))
    elif parent.commission_percent:
        child.commission_percent = parent.commission_percent
    else:
        child.commission_percent = ps.get_int("reseller.default_commission_percent", 0)
    db.commit()
    db.refresh(child)
    return child


def update_sub_reseller(
    db: Session,
    parent: Admin,
    child: Admin,
    *,
    max_users: Optional[int] = None,
    max_nodes: Optional[int] = None,
    commission_percent: Optional[int] = None,
    password: Optional[str] = None,
) -> Admin:
    if child.parent_admin_id != parent.id:
        raise HTTPException(status_code=403, detail="Not your sub-reseller")
    if max_users is not None:
        child.max_users = clamp_child_quota(parent.max_users, max_users)
    if max_nodes is not None:
        child.max_nodes = clamp_child_quota(parent.max_nodes, max_nodes)
    if commission_percent is not None:
        child.commission_percent = max(0, min(100, int(commission_percent)))
    if password:
        from passlib.context import CryptContext

        child.hashed_password = CryptContext(schemes=["bcrypt"], deprecated="auto").hash(password)
    db.commit()
    db.refresh(child)
    return child


def assert_manages_admin(db: Session, actor, target: Admin) -> None:
    if getattr(actor, "is_sudo", False):
        return
    actor_row = db_admin(db, actor)
    if actor_row is None:
        raise HTTPException(status_code=403, detail="Not allowed")
    if target.parent_admin_id == actor_row.id:
        return
    if target.id == actor_row.id:
        return
    raise HTTPException(status_code=403, detail="Not allowed to manage this account")


def onboarding_status(db: Session, admin) -> dict:
    """Reseller first-run checklist."""
    from app import feature_flags, tenant as tenant_svc

    dbadmin = db_admin(db, admin)
    if dbadmin is None or getattr(admin, "is_sudo", False):
        return {"show_wizard": False, "completed": True, "steps": {}}

    completed = feature_flags.is_enabled("reseller_onboarding_completed", admin_id=dbadmin.id)
    branding = tenant_svc.resolve_branding(db, dbadmin.tenant_id)
    has_branding = bool(branding.get("panel_title") and branding["panel_title"] != "Shahkar")
    from sqlalchemy import or_

    plan_filters = [Plan.owner_admin_id == dbadmin.id]
    if dbadmin.tenant_id is not None:
        plan_filters.append(Plan.tenant_id == dbadmin.tenant_id)
    has_plan = db.query(Plan).filter(or_(*plan_filters)).first() is not None
    has_user = db.query(User).filter(User.admin_id == dbadmin.id).count() > 0
    steps = {"branding": has_branding, "plan": has_plan, "user": has_user}
    all_done = all(steps.values())
    return {
        "show_wizard": not completed and not all_done,
        "completed": completed or all_done,
        "steps": steps,
    }


def complete_onboarding(db: Session, admin) -> None:
    from app import feature_flags

    dbadmin = db_admin(db, admin)
    if dbadmin is None:
        raise HTTPException(status_code=400, detail="Admin not found")
    feature_flags.set_flag("reseller_onboarding_completed", True, admin_id=dbadmin.id)
