"""Reseller prepaid traffic packages: catalog, purchase, and manual credit."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import billing
from app import platform_settings as ps
from app.db.models import (
    Admin,
    ResellerTrafficPackage,
    ResellerTrafficPackageOverride,
    ResellerTrafficPurchase,
    Transaction,
    Wallet,
)


class TrafficPackageError(Exception):
    """Domain error for traffic package operations (mapped to HTTP by routers)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def list_packages(
    db: Session,
    *,
    enabled_only: bool = False,
) -> List[ResellerTrafficPackage]:
    q = db.query(ResellerTrafficPackage).order_by(ResellerTrafficPackage.id.asc())
    if enabled_only:
        q = q.filter(ResellerTrafficPackage.enabled.is_(True))
    return q.all()


def get_package(db: Session, package_id: int) -> Optional[ResellerTrafficPackage]:
    return (
        db.query(ResellerTrafficPackage)
        .filter(ResellerTrafficPackage.id == package_id)
        .first()
    )


def get_override(
    db: Session,
    *,
    admin_id: int,
    package_id: int,
) -> Optional[ResellerTrafficPackageOverride]:
    return (
        db.query(ResellerTrafficPackageOverride)
        .filter(
            ResellerTrafficPackageOverride.admin_id == admin_id,
            ResellerTrafficPackageOverride.package_id == package_id,
        )
        .first()
    )


def effective_usage_rate_per_gb(admin: Optional[Admin] = None) -> int:
    """PAYG rate: admin override if set, else platform billing.usage_rate_per_gb."""
    if admin is not None and getattr(admin, "usage_rate_per_gb", None) is not None:
        return int(admin.usage_rate_per_gb)
    return int(ps.get_int("billing.usage_rate_per_gb", 0) or 0)


def effective_package_offer(
    db: Session,
    admin: Admin,
    pkg: ResellerTrafficPackage,
) -> Dict[str, Any]:
    """Resolve catalog package with optional per-reseller price/bytes overrides."""
    ov = get_override(db, admin_id=admin.id, package_id=pkg.id)
    catalog_price = int(pkg.price or 0)
    catalog_bytes = int(pkg.bytes or 0)
    price = catalog_price
    bytes_ = catalog_bytes
    price_overridden = False
    bytes_overridden = False
    if ov is not None:
        if ov.price is not None:
            price = int(ov.price)
            price_overridden = True
        if ov.bytes is not None:
            bytes_ = int(ov.bytes)
            bytes_overridden = True
    return {
        "id": pkg.id,
        "name": pkg.name,
        "enabled": bool(pkg.enabled),
        "created_at": pkg.created_at,
        "catalog_price": catalog_price,
        "catalog_bytes": catalog_bytes,
        "price": price,
        "bytes": bytes_,
        "price_overridden": price_overridden,
        "bytes_overridden": bytes_overridden,
        "overridden": price_overridden or bytes_overridden,
    }


def list_packages_for_admin(
    db: Session,
    admin: Admin,
    *,
    enabled_only: bool = False,
) -> List[Dict[str, Any]]:
    packages = list_packages(db, enabled_only=enabled_only)
    return [effective_package_offer(db, admin, pkg) for pkg in packages]


def upsert_package_override(
    db: Session,
    *,
    admin_id: int,
    package_id: int,
    price: Optional[int],
    bytes: Optional[int],
    commit: bool = False,
) -> Optional[ResellerTrafficPackageOverride]:
    """Set or clear override fields. Both null removes the row."""
    if price is not None and int(price) < 0:
        raise TrafficPackageError("Override price cannot be negative")
    if bytes is not None and int(bytes) <= 0:
        raise TrafficPackageError("Override bytes must be positive")

    ov = get_override(db, admin_id=admin_id, package_id=package_id)
    if price is None and bytes is None:
        if ov is not None:
            db.delete(ov)
            if commit:
                db.commit()
        return None

    if ov is None:
        ov = ResellerTrafficPackageOverride(
            admin_id=admin_id,
            package_id=package_id,
            price=int(price) if price is not None else None,
            bytes=int(bytes) if bytes is not None else None,
        )
        db.add(ov)
    else:
        ov.price = int(price) if price is not None else None
        ov.bytes = int(bytes) if bytes is not None else None
    if commit:
        db.commit()
        db.refresh(ov)
    return ov


def create_package(
    db: Session,
    *,
    name: str,
    bytes: Optional[int] = None,
    price: Optional[int] = None,
    enabled: bool = True,
) -> ResellerTrafficPackage:
    if not name or not name.strip():
        raise TrafficPackageError("Package name is required")
    resolved_bytes = int(bytes) if bytes is not None else int(
        ps.get_int("billing.default_package_bytes", 0) or 0
    )
    resolved_price = int(price) if price is not None else int(
        ps.get_int("billing.default_package_price", 0) or 0
    )
    if resolved_bytes <= 0:
        raise TrafficPackageError("Package bytes must be positive")
    if resolved_price < 0:
        raise TrafficPackageError("Package price cannot be negative")
    pkg = ResellerTrafficPackage(
        name=name.strip(),
        bytes=resolved_bytes,
        price=resolved_price,
        enabled=bool(enabled),
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg


def update_package(
    db: Session,
    pkg: ResellerTrafficPackage,
    *,
    name: Optional[str] = None,
    bytes: Optional[int] = None,
    price: Optional[int] = None,
    enabled: Optional[bool] = None,
) -> ResellerTrafficPackage:
    if name is not None:
        if not name.strip():
            raise TrafficPackageError("Package name is required")
        pkg.name = name.strip()
    if bytes is not None:
        if int(bytes) <= 0:
            raise TrafficPackageError("Package bytes must be positive")
        pkg.bytes = int(bytes)
    if price is not None:
        if int(price) < 0:
            raise TrafficPackageError("Package price cannot be negative")
        pkg.price = int(price)
    if enabled is not None:
        pkg.enabled = bool(enabled)
    db.commit()
    db.refresh(pkg)
    return pkg


def delete_package(db: Session, pkg: ResellerTrafficPackage) -> None:
    """Soft-disable when purchased before; otherwise hard-delete."""
    used = (
        db.query(ResellerTrafficPurchase)
        .filter(ResellerTrafficPurchase.package_id == pkg.id)
        .count()
    )
    if used:
        pkg.enabled = False
        db.commit()
        return
    (
        db.query(ResellerTrafficPackageOverride)
        .filter(ResellerTrafficPackageOverride.package_id == pkg.id)
        .delete(synchronize_session=False)
    )
    db.delete(pkg)
    db.commit()


def purchase_package(
    db: Session,
    *,
    admin_id: int,
    package_id: int,
    created_by_admin_id: Optional[int] = None,
) -> ResellerTrafficPurchase:
    billing.get_or_create_wallet(db, admin_id)

    pkg = (
        db.query(ResellerTrafficPackage)
        .filter(
            ResellerTrafficPackage.id == package_id,
            ResellerTrafficPackage.enabled.is_(True),
        )
        .with_for_update()
        .first()
    )
    if pkg is None:
        raise TrafficPackageError("Traffic package not found or disabled", 404)

    admin = (
        db.query(Admin)
        .filter(Admin.id == admin_id, Admin.is_sudo.is_(False))
        .with_for_update()
        .first()
    )
    if admin is None:
        raise TrafficPackageError("Reseller not found", 404)

    wallet = (
        db.query(Wallet)
        .filter(Wallet.admin_id == admin_id)
        .with_for_update()
        .first()
    )
    if wallet is None:
        raise TrafficPackageError("Wallet not found", 404)

    offer = effective_package_offer(db, admin, pkg)
    price = int(offer["price"])
    granted_bytes = int(offer["bytes"])
    if granted_bytes <= 0:
        raise TrafficPackageError("Package bytes must be positive")

    if wallet.balance < price:
        raise TrafficPackageError(
            f"Insufficient wallet balance (need {price}, have {wallet.balance})"
        )

    if price > 0:
        tx = Transaction(
            admin_id=admin_id,
            amount=-price,
            type="traffic_package",
            description=f"Traffic package: {pkg.name} ({granted_bytes} bytes)",
            reference=f"traffic_package:{pkg.id}",
        )
        db.add(tx)
        wallet.balance -= price

    admin.prepaid_traffic_remaining = int(admin.prepaid_traffic_remaining or 0) + granted_bytes
    purchase = ResellerTrafficPurchase(
        admin_id=admin_id,
        package_id=pkg.id,
        bytes=granted_bytes,
        price_paid=price,
        source="purchase",
        created_by_admin_id=created_by_admin_id or admin_id,
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)

    if price > 0:
        from app.billing.commission import credit_parent_commission

        credit_parent_commission(
            db,
            admin_id,
            -price,
            tx_type="traffic_package",
            description=f"Traffic package: {pkg.name}",
            reference=f"traffic_package:{pkg.id}",
        )
    return purchase


def credit_traffic(
    db: Session,
    *,
    admin_id: int,
    bytes: int,
    created_by_admin_id: Optional[int] = None,
    description: Optional[str] = None,
) -> ResellerTrafficPurchase:
    if int(bytes) <= 0:
        raise TrafficPackageError("Credit bytes must be positive")

    admin = (
        db.query(Admin)
        .filter(Admin.id == admin_id, Admin.is_sudo.is_(False))
        .with_for_update()
        .first()
    )
    if admin is None:
        raise TrafficPackageError("Reseller not found", 404)

    admin.prepaid_traffic_remaining = int(admin.prepaid_traffic_remaining or 0) + int(bytes)
    purchase = ResellerTrafficPurchase(
        admin_id=admin_id,
        package_id=None,
        bytes=int(bytes),
        price_paid=0,
        source="manual",
        created_by_admin_id=created_by_admin_id,
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return purchase


def list_purchases(
    db: Session,
    *,
    admin_id: Optional[int] = None,
    limit: int = 100,
) -> List[ResellerTrafficPurchase]:
    q = db.query(ResellerTrafficPurchase).order_by(ResellerTrafficPurchase.id.desc())
    if admin_id is not None:
        q = q.filter(ResellerTrafficPurchase.admin_id == admin_id)
    return q.limit(max(1, min(int(limit), 500))).all()


def get_reseller_pricing(db: Session, admin: Admin) -> Dict[str, Any]:
    """Sudo view: effective rate + packages with catalog vs effective fields."""
    platform_rate = int(ps.get_int("billing.usage_rate_per_gb", 0) or 0)
    admin_rate = getattr(admin, "usage_rate_per_gb", None)
    return {
        "username": admin.username,
        "usage_rate_per_gb": int(admin_rate) if admin_rate is not None else None,
        "effective_usage_rate_per_gb": effective_usage_rate_per_gb(admin),
        "platform_usage_rate_per_gb": platform_rate,
        "packages": list_packages_for_admin(db, admin, enabled_only=False),
    }


def set_reseller_pricing(
    db: Session,
    admin: Admin,
    *,
    usage_rate_per_gb: Optional[int] = None,
    clear_usage_rate: bool = False,
    packages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Apply PAYG rate and/or package overrides for one reseller."""
    if clear_usage_rate:
        admin.usage_rate_per_gb = None
    elif usage_rate_per_gb is not None:
        if int(usage_rate_per_gb) < 0:
            raise TrafficPackageError("usage_rate_per_gb cannot be negative")
        admin.usage_rate_per_gb = int(usage_rate_per_gb)

    for item in packages or []:
        package_id = int(item["package_id"])
        pkg = get_package(db, package_id)
        if pkg is None:
            raise TrafficPackageError(f"Traffic package {package_id} not found", 404)
        upsert_package_override(
            db,
            admin_id=admin.id,
            package_id=package_id,
            price=item.get("price"),
            bytes=item.get("bytes"),
            commit=False,
        )

    db.commit()
    db.refresh(admin)
    return get_reseller_pricing(db, admin)
