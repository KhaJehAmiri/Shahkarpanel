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
    # Sudo admins (incl. the env-based SUDO_USERNAME, which has no `admins` row)
    # are unlimited and must never be blocked by the reseller node quota.
    if getattr(admin, "is_sudo", False):
        return
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


def list_protocol_capability_nodes(db: Session, admin) -> List[Node]:
    """Nodes that decide which protocols a caller may assign to users.

    Resellers manage only their workspace nodes in Infrastructure, but user
    creation rides the shared main-panel fleet (``tenant_id`` / ``owner_admin_id``
    both NULL). Include those platform nodes so WireGuard / Finalmask / sing-box
    toggles match what sudo sees on the main panel.
    """
    from sqlalchemy import and_, or_

    if getattr(admin, "is_sudo", False):
        return db.query(Node).order_by(Node.id).all()

    clauses = [and_(Node.tenant_id.is_(None), Node.owner_admin_id.is_(None))]
    scoped = list_scoped_nodes(db, admin)
    if scoped:
        clauses.append(Node.id.in_([n.id for n in scoped]))
    return db.query(Node).filter(or_(*clauses)).order_by(Node.id).all()


def assignable_native_protocols(db: Session, admin) -> Dict[str, bool]:
    """Booleans for native protocols assignable from the shared/workspace fleet.

    Mirrors ``protocolAssignable`` in the dashboard (Finalmask / plain WG /
    AmneziaWG / sing-box) so resellers see the same toggles as the main panel.
    """
    from app.models.node import CoreKind
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

    wireguard = False
    amneziawg = False
    hysteria2 = False
    tuic = False
    anytls = False

    for node in list_protocol_capability_nodes(db, admin):
        wg = node.wireguard
        if wg is not None:
            if getattr(wg, "xray_wg_enabled", False):
                wireguard = True
            elif plain_wg_enabled(wg) and (node.core_kind or "") == CoreKind.wireguard.value:
                wireguard = True
            if amneziawg_enabled(wg):
                amneziawg = True

        sb = node.singbox
        if sb is not None:
            if getattr(sb, "hysteria2_enabled", False):
                hysteria2 = True
            if getattr(sb, "tuic_enabled", False):
                tuic = True
            if getattr(sb, "anytls_enabled", False):
                anytls = True

    return {
        "wireguard": wireguard,
        "amneziawg": amneziawg,
        "hysteria2": hysteria2,
        "tuic": tuic,
        "anytls": anytls,
    }


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
    from app import billing, feature_flags, platform_settings as ps
    from app.db.models import Transaction

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
    wallet_blocked = False
    usage_rate_per_gb = 0
    pending_usage_cost = 0
    pending_usage_bytes = 0
    currency_label: Optional[str] = None
    last_usage_debit: Optional[Dict[str, Any]] = None
    capped_users = 0

    users_usage = int(dbadmin.users_usage or 0) if dbadmin else 0
    max_total_traffic = dbadmin.max_total_traffic if dbadmin else None
    traffic_remaining: Optional[int] = None
    if max_total_traffic is not None:
        traffic_remaining = max(0, int(max_total_traffic) - users_usage)

    if feature_flags.is_enabled("billing") and dbadmin and wallet_balance is not None:
        from app.billing.usage_billing import usage_summary_for_admin, wallet_is_low

        usage_rate_per_gb = ps.get_int("billing.usage_rate_per_gb", 0)
        wallet_low = wallet_is_low(wallet_balance)
        currency_label = (ps.get_setting("billing.currency_label") or "").strip() or None
        summary = usage_summary_for_admin(db, dbadmin, rate_per_gb=usage_rate_per_gb)
        pending_usage_cost = int(summary.get("estimated_cost") or 0)
        pending_usage_bytes = int(summary.get("owned_bytes") or 0) + int(
            summary.get("foreign_bytes") or 0
        )
        wallet_blocked = bool(summary.get("wallet_blocked"))
        capped_users = (
            db.query(User)
            .filter(User.admin_id == dbadmin.id, User.capped_by_reseller.is_(True))
            .count()
        )
        last_tx = (
            db.query(Transaction)
            .filter(
                Transaction.admin_id == dbadmin.id,
                Transaction.type == "usage_billing",
            )
            .order_by(Transaction.id.desc())
            .first()
        )
        if last_tx is not None:
            last_usage_debit = {
                "id": last_tx.id,
                "amount": last_tx.amount,
                "description": last_tx.description,
                "created_at": last_tx.created_at.isoformat() if last_tx.created_at else None,
            }

    prepaid_traffic_remaining = (
        int(getattr(dbadmin, "prepaid_traffic_remaining", 0) or 0) if dbadmin else 0
    )

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
        "wallet_blocked": wallet_blocked,
        "usage_rate_per_gb": usage_rate_per_gb,
        "users_usage": users_usage,
        "max_total_traffic": max_total_traffic,
        "traffic_remaining": traffic_remaining,
        "prepaid_traffic_remaining": prepaid_traffic_remaining,
        "pending_usage_cost": pending_usage_cost,
        "pending_usage_bytes": pending_usage_bytes,
        "capped_users": capped_users,
        "currency_label": currency_label,
        "last_usage_debit": last_usage_debit,
    }
