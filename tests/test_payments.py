"""Phase 4: payment intents, top-up and portal direct pay."""
import secrets

from passlib.context import CryptContext

from app.billing.payments import (
    complete_payment,
    create_portal_payment,
    create_topup_payment,
    list_online_providers,
)
from app.db import GetDB, crud
from app.db.models import Admin as DBAdmin
from app.db.models import Plan
from app.models.proxy import ProxyTypes
from app.models.user import UserCreate, UserStatus

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _reseller(db):
    admin = DBAdmin(
        username=f"rs{secrets.token_hex(4)}",
        hashed_password=pwd.hash("x"),
        is_sudo=False,
        role="reseller",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _user(db, admin):
    return crud.create_user(
        db,
        UserCreate(
            username=f"u{secrets.token_hex(4)}",
            proxies={ProxyTypes.VMess: {"id": "00000000-0000-0000-0000-000000000099"}},
            status=UserStatus.active,
            inbounds={},
        ),
        admin=admin,
    )


def test_online_providers_include_demo():
    names = list_online_providers()
    assert "demo" in names
    assert "manual" not in names


def test_topup_credits_wallet():
    with GetDB() as db:
        admin = _reseller(db)
        intent, payload = create_topup_payment(db, admin.id, 5000, "demo")
        assert payload.get("confirm_token")
        intent = complete_payment(db, intent, {"confirm_token": payload["confirm_token"]})
        assert intent.status == "completed"
        from app import billing

        wallet = billing.get_or_create_wallet(db, admin.id)
        assert wallet.balance == 5000


def test_portal_direct_pay_renews_without_wallet_debit():
    with GetDB() as db:
        admin = _reseller(db)
        user = _user(db, admin)
        plan = Plan(
            name=f"p{secrets.token_hex(3)}",
            price=2000,
            duration_days=30,
            owner_admin_id=admin.id,
            enabled=True,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)

        from app import billing

        billing.add_transaction(db, admin.id, 100, type="credit")
        old_expire = user.expire

        intent, payload = create_portal_payment(db, user, plan.id, "demo")
        complete_payment(db, intent, {"confirm_token": payload["confirm_token"]})

        wallet = billing.get_or_create_wallet(db, admin.id)
        assert wallet.balance == 100

        db.refresh(user)
        assert user.expire != old_expire or user.expire is not None
