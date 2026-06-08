"""Commercial plan scoping per reseller workspace."""
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Query, Session

from app.db.models import Admin, Plan
from app.tenant import admin_tenant_id


def reseller_plan_scope(db: Session, admin) -> Tuple[Optional[int], Optional[int]]:
    """Return (tenant_id, owner_admin_id) for plan ownership checks."""
    if getattr(admin, "is_sudo", False):
        return None, None
    dbadmin = db.query(Admin).filter(Admin.username == admin.username).first()
    if dbadmin is None:
        raise HTTPException(status_code=400, detail="Admin not found in database")
    tenant_id = admin_tenant_id(db, admin)
    return tenant_id, dbadmin.id


def scope_plans_query(
    query: Query,
    *,
    tenant_id: Optional[int],
    owner_admin_id: Optional[int],
    sudo: bool = False,
) -> Query:
    """Limit a Plan query to a reseller catalog. Sudo sees everything."""
    if sudo:
        return query
    clauses = []
    if tenant_id is not None:
        clauses.append(Plan.tenant_id == tenant_id)
    if owner_admin_id is not None:
        clauses.append(Plan.owner_admin_id == owner_admin_id)
    if not clauses:
        return query.filter(False)
    from sqlalchemy import or_

    return query.filter(or_(*clauses))


def get_scoped_plans(
    db: Session,
    admin,
    *,
    enabled_only: bool = False,
) -> List[Plan]:
    q = db.query(Plan)
    if enabled_only:
        q = q.filter(Plan.enabled.is_(True))
    tenant_id, owner_admin_id = reseller_plan_scope(db, admin)
    q = scope_plans_query(
        q,
        tenant_id=tenant_id,
        owner_admin_id=owner_admin_id,
        sudo=getattr(admin, "is_sudo", False),
    )
    return q.order_by(Plan.id).all()


def get_plans_for_user_reseller(
    db: Session,
    admin_id: int,
    *,
    enabled_only: bool = True,
) -> List[Plan]:
    """Plans visible to an end-user via their owning reseller."""
    dbadmin = db.query(Admin).filter(Admin.id == admin_id).first()
    if dbadmin is None:
        return []
    tenant_id = dbadmin.tenant_id
    q = db.query(Plan)
    if enabled_only:
        q = q.filter(Plan.enabled.is_(True))
    clauses = []
    if tenant_id is not None:
        clauses.append(Plan.tenant_id == tenant_id)
    clauses.append(Plan.owner_admin_id == admin_id)
    from sqlalchemy import or_

    return q.filter(or_(*clauses)).order_by(Plan.id).all()


def assert_plan_accessible(db: Session, admin, plan: Plan) -> None:
    if getattr(admin, "is_sudo", False):
        return
    tenant_id, owner_admin_id = reseller_plan_scope(db, admin)
    ok = False
    if tenant_id is not None and plan.tenant_id == tenant_id:
        ok = True
    if owner_admin_id is not None and plan.owner_admin_id == owner_admin_id:
        ok = True
    if not ok:
        raise HTTPException(status_code=403, detail="Plan not in your catalog")


def assert_plan_for_user(db: Session, user_admin_id: int, plan: Plan) -> None:
    dbadmin = db.query(Admin).filter(Admin.id == user_admin_id).first()
    if dbadmin is None:
        raise HTTPException(status_code=400, detail="User has no owning reseller")
    ok = False
    if dbadmin.tenant_id is not None and plan.tenant_id == dbadmin.tenant_id:
        ok = True
    if plan.owner_admin_id == user_admin_id:
        ok = True
    if not ok:
        raise HTTPException(status_code=403, detail="Plan not available for this user")


def plan_name_taken(
    db: Session,
    name: str,
    *,
    tenant_id: Optional[int],
    owner_admin_id: Optional[int],
    exclude_id: Optional[int] = None,
) -> bool:
    q = db.query(Plan).filter(Plan.name == name)
    if tenant_id is None:
        q = q.filter(Plan.tenant_id.is_(None))
    else:
        q = q.filter(Plan.tenant_id == tenant_id)
    if owner_admin_id is None:
        q = q.filter(Plan.owner_admin_id.is_(None))
    else:
        q = q.filter(Plan.owner_admin_id == owner_admin_id)
    if exclude_id is not None:
        q = q.filter(Plan.id != exclude_id)
    return q.first() is not None
