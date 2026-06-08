"""Reseller workspace helpers: quotas, node ownership, KPIs."""
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import Admin, Node, User
from app.tenant import admin_tenant_id, get_tenant, scope_nodes_query


def db_admin(db: Session, admin) -> Optional[Admin]:
    return crud.get_admin(db, admin.username)


def count_users_for_admin(db: Session, dbadmin: Admin) -> int:
    return db.query(User).filter(User.admin_id == dbadmin.id).count()


def count_owned_nodes(db: Session, dbadmin: Admin, tenant_id: Optional[int]) -> int:
    q = db.query(Node)
    if tenant_id is not None:
        q = scope_nodes_query(q, tenant_id)
    else:
        q = q.filter(Node.owner_admin_id == dbadmin.id)
    return q.count()


def resolve_max_nodes(db: Session, dbadmin: Admin, tenant_id: Optional[int]) -> Optional[int]:
    limits = []
    if dbadmin.max_nodes is not None:
        limits.append(dbadmin.max_nodes)
    if tenant_id is not None:
        tenant = get_tenant(db, tenant_id)
        if tenant and tenant.max_nodes is not None:
            limits.append(tenant.max_nodes)
    if not limits:
        return None
    return min(limits)


def resolve_max_users(db: Session, dbadmin: Admin, tenant_id: Optional[int]) -> Optional[int]:
    limits = []
    if dbadmin.max_users is not None:
        limits.append(dbadmin.max_users)
    if tenant_id is not None:
        tenant = get_tenant(db, tenant_id)
        if tenant and tenant.max_users is not None:
            limits.append(tenant.max_users)
    if not limits:
        return None
    return min(limits)


def assert_can_add_node(db: Session, admin) -> None:
    dbadmin = db_admin(db, admin)
    if dbadmin is None:
        raise HTTPException(status_code=400, detail="Admin not found in database")
    tenant_id = admin_tenant_id(db, admin)
    max_nodes = resolve_max_nodes(db, dbadmin, tenant_id)
    if max_nodes is None:
        return
    current = count_owned_nodes(db, dbadmin, tenant_id)
    if current >= max_nodes:
        raise HTTPException(
            status_code=400,
            detail=f"Node limit reached ({current}/{max_nodes})",
        )


def scoped_nodes_query(db: Session, admin):
    if getattr(admin, "is_sudo", False):
        return db.query(Node)
    dbadmin = db_admin(db, admin)
    if dbadmin is None:
        return db.query(Node).filter(False)
    tenant_id = admin_tenant_id(db, admin)
    if tenant_id is not None:
        return scope_nodes_query(db.query(Node), tenant_id)
    return db.query(Node).filter(Node.owner_admin_id == dbadmin.id)


def list_scoped_nodes(db: Session, admin) -> List[Node]:
    return scoped_nodes_query(db, admin).order_by(Node.id).all()


def admin_owns_node(db: Session, admin, node: Node) -> bool:
    if getattr(admin, "is_sudo", False):
        return True
    dbadmin = db_admin(db, admin)
    if dbadmin is None:
        return False
    tenant_id = admin_tenant_id(db, admin)
    if tenant_id is not None:
        return node.tenant_id == tenant_id
    return node.owner_admin_id == dbadmin.id


def assert_owns_node(db: Session, admin, node: Node) -> None:
    if not admin_owns_node(db, admin, node):
        raise HTTPException(status_code=403, detail="Node not in your workspace")


def workspace_summary(db: Session, admin) -> Dict[str, Any]:
    from app import billing, feature_flags

    dbadmin = db_admin(db, admin)
    tenant_id = admin_tenant_id(db, admin) if dbadmin else None
    tenant = get_tenant(db, tenant_id) if tenant_id else None

    wallet_balance: Optional[int] = None
    if feature_flags.is_enabled("billing") and dbadmin:
        wallet = billing.get_or_create_wallet(db, dbadmin.id)
        wallet_balance = wallet.balance

    users_count = count_users_for_admin(db, dbadmin) if dbadmin else 0
    nodes_count = count_owned_nodes(db, dbadmin, tenant_id) if dbadmin else 0

    wallet_low = False
    usage_rate_per_gb = 0
    if feature_flags.is_enabled("billing") and dbadmin and wallet_balance is not None:
        from app.billing.usage_billing import wallet_is_low
        from app import platform_settings as ps

        usage_rate_per_gb = ps.get_int("billing.usage_rate_per_gb", 0)
        wallet_low = wallet_is_low(wallet_balance)

    return {
        "username": admin.username,
        "role": getattr(admin, "role", None) or "reseller",
        "tenant_id": tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "tenant_slug": tenant.slug if tenant else None,
        "byo_node_discount_percent": tenant.byo_node_discount_percent if tenant else 0,
        "users_count": users_count,
        "max_users": resolve_max_users(db, dbadmin, tenant_id) if dbadmin else None,
        "nodes_count": nodes_count,
        "max_nodes": resolve_max_nodes(db, dbadmin, tenant_id) if dbadmin else None,
        "wallet_balance": wallet_balance,
        "wallet_low": wallet_low,
        "usage_rate_per_gb": usage_rate_per_gb,
        "users_usage": dbadmin.users_usage if dbadmin else 0,
        "max_total_traffic": dbadmin.max_total_traffic if dbadmin else None,
    }
