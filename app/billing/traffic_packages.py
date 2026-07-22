"""Reseller prepaid traffic packages: catalog, purchase, and manual credit."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app import billing
from app.db.models import (
    Admin,
    ResellerTrafficPackage,
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


def create_package(
    db: Session,
    *,
    name: str,
    bytes: int,
    price: int,
    enabled: bool = True,
) -> ResellerTrafficPackage:
    if not name or not name.strip():
        raise TrafficPackageError("Package name is required")
    if int(bytes) <= 0:
        raise TrafficPackageError("Package bytes must be positive")
    if int(price) < 0:
        raise TrafficPackageError("Package price cannot be negative")
    pkg = ResellerTrafficPackage(
        name=name.strip(),
        bytes=int(bytes),
        price=int(price),
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

    price = int(pkg.price or 0)
    if wallet.balance < price:
        raise TrafficPackageError(
            f"Insufficient wallet balance (need {price}, have {wallet.balance})"
        )

    if price > 0:
        tx = Transaction(
            admin_id=admin_id,
            amount=-price,
            type="traffic_package",
            description=f"Traffic package: {pkg.name} ({pkg.bytes} bytes)",
            reference=f"traffic_package:{pkg.id}",
        )
        db.add(tx)
        wallet.balance -= price

    admin.prepaid_traffic_remaining = int(admin.prepaid_traffic_remaining or 0) + int(pkg.bytes)
    purchase = ResellerTrafficPurchase(
        admin_id=admin_id,
        package_id=pkg.id,
        bytes=int(pkg.bytes),
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
