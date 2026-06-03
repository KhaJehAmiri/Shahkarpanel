from app import api_keys, billing
from app.db import GetDB, crud
from app.db.models import Admin as DBAdmin
from app.models.admin import Admin
from app.rbac import has_permission, role_permissions


def _make_admin(username, is_sudo=False, role=None):
    with GetDB() as db:
        admin = DBAdmin(username=username, hashed_password="x", is_sudo=is_sudo, role=role)
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin.id


# ---- RBAC ----

def test_sudo_has_all_permissions():
    admin = Admin(username="root", is_sudo=True)
    assert admin.has_permission("billing:write")
    assert admin.has_permission("admins:write")


def test_reseller_permissions_are_scoped():
    admin = Admin(username="r1", is_sudo=False, role="reseller")
    assert has_permission(admin, "users:write")
    assert has_permission(admin, "billing:read")
    assert not has_permission(admin, "billing:write")
    assert not has_permission(admin, "admins:write")


def test_support_is_read_only():
    perms = role_permissions("support")
    assert "users:read" in perms
    assert "users:write" not in perms


# ---- Plans ----

def test_plan_crud():
    with GetDB() as db:
        plan = crud.create_plan(
            db, name="pro-100", price=1500, data_limit=100 * 1024**3, duration_days=30
        )
        assert plan.id is not None
        plan = crud.update_plan(db, plan, price=2000)
        assert plan.price == 2000
        assert any(p.name == "pro-100" for p in crud.get_plans(db))
        crud.remove_plan(db, plan)
        assert not any(p.name == "pro-100" for p in crud.get_plans(db))


# ---- Billing ----

def test_wallet_credit_and_invoice_charge():
    admin_id = _make_admin("billing-admin")
    with GetDB() as db:
        wallet = billing.get_or_create_wallet(db, admin_id)
        assert wallet.balance == 0

        billing.add_transaction(db, admin_id, 5000, type="credit", description="topup")
        wallet = billing.get_or_create_wallet(db, admin_id)
        assert wallet.balance == 5000

        invoice = billing.create_invoice(db, admin_id, 1200)
        assert invoice.status == "pending"

        invoice = billing.pay_invoice(db, invoice)
        assert invoice.status == "paid"
        assert invoice.paid_at is not None

        wallet = billing.get_or_create_wallet(db, admin_id)
        assert wallet.balance == 5000 - 1200


def test_pay_invoice_is_idempotent():
    admin_id = _make_admin("billing-admin-2")
    with GetDB() as db:
        invoice = billing.create_invoice(db, admin_id, 1000)
        billing.pay_invoice(db, invoice)
        billing.pay_invoice(db, invoice)  # second call must not double-charge
        wallet = billing.get_or_create_wallet(db, admin_id)
        assert wallet.balance == -1000


# ---- API keys ----

def test_api_key_create_and_authenticate():
    admin_id = _make_admin("apikey-admin")
    with GetDB() as db:
        record, raw = api_keys.create_api_key(db, admin_id, "ci", scopes=["users:read"])
        assert raw.startswith("nxp_")
        assert record.key_hash != raw  # only the hash is stored

        authed = api_keys.authenticate_api_key(db, raw)
        assert authed is not None
        assert authed.admin_id == admin_id

        assert api_keys.authenticate_api_key(db, "nxp_bogus_key") is None


def test_revoked_api_key_rejected():
    admin_id = _make_admin("apikey-admin-2")
    with GetDB() as db:
        record, raw = api_keys.create_api_key(db, admin_id, "tmp")
        record.revoked = True
        db.commit()
        assert api_keys.authenticate_api_key(db, raw) is None
