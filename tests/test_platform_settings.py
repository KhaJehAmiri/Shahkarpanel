"""Phase 6 commercial: platform settings DB + sub-reseller commission."""
import secrets

from passlib.context import CryptContext

from app import billing, platform_settings as ps
from app.billing.commission import credit_parent_commission
from app.billing.providers import reload_providers
from app.db import GetDB
from app.db.models import Admin as DBAdmin
from app.tenant.sub_reseller import create_sub_reseller, update_sub_reseller

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _parent(db):
    admin = DBAdmin(
        username=f"p{secrets.token_hex(4)}",
        hashed_password=pwd.hash("x"),
        is_sudo=False,
        role="reseller",
        max_users=100,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def test_platform_settings_roundtrip():
    key = "billing.usage_rate_per_gb"
    old = ps.get_int(key, 0)
    try:
        ps.set_setting(key, 42)
        ps.invalidate_cache()
        assert ps.get_int(key) == 42
        rows = ps.list_settings_for_ui()
        assert any(r["key"] == key and r["is_set"] for r in rows)
    finally:
        ps.set_setting(key, old)
        ps.invalidate_cache()


def test_reload_providers_respects_demo_flag():
    old = ps.get_bool("payment.demo_enabled", True)
    try:
        ps.set_setting("payment.demo_enabled", False)
        ps.invalidate_cache()
        reload_providers()
        from app.billing.providers import available_providers

        assert "demo" not in available_providers()
    finally:
        ps.set_setting("payment.demo_enabled", old)
        ps.invalidate_cache()
        reload_providers()


def test_commission_credits_parent():
    with GetDB() as db:
        parent = _parent(db)
        child = create_sub_reseller(
            db,
            parent,
            username=f"c{secrets.token_hex(4)}",
            password="x",
            commission_percent=10,
        )
        billing.add_transaction(db, child.id, 10000, type="credit")
        billing.add_transaction(
            db,
            child.id,
            -1000,
            type="usage_billing",
            description="test",
            reference="ref-1",
        )
        parent_wallet = billing.get_or_create_wallet(db, parent.id)
        assert parent_wallet.balance == 100


def test_update_sub_reseller_commission():
    with GetDB() as db:
        parent = _parent(db)
        child = create_sub_reseller(
            db,
            parent,
            username=f"c{secrets.token_hex(4)}",
            password="x",
        )
        updated = update_sub_reseller(db, parent, child, commission_percent=25)
        assert updated.commission_percent == 25


def test_credit_parent_commission_standalone():
    with GetDB() as db:
        parent = _parent(db)
        child = create_sub_reseller(
            db,
            parent,
            username=f"c{secrets.token_hex(4)}",
            password="x",
            commission_percent=20,
        )
        credit_parent_commission(
            db,
            child.id,
            -500,
            tx_type="usage_billing",
            description="standalone",
            reference="ref-2",
        )
        wallet = billing.get_or_create_wallet(db, parent.id)
        assert wallet.balance == 100
