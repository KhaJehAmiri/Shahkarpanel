"""Tenant-scoped commercial plans."""
import secrets

from passlib.context import CryptContext

from app.db import GetDB, crud
from app.db.models import Admin as DBAdmin
from app.db.models import Plan
from app.models.admin import Admin
from app.models.proxy import ProxyTypes
from app.models.user import UserCreate, UserStatus
from app.tenant.plan_ops import (
    assert_plan_accessible,
    get_plans_for_user_reseller,
    get_scoped_plans,
    plan_name_taken,
)

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _reseller(db):
    name = f"rs-{secrets.token_hex(3)}"
    admin = DBAdmin(
        username=name,
        hashed_password=pwd.hash("x"),
        is_sudo=False,
        role="reseller",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _plan(db, name, owner_admin_id=None, tenant_id=None, enabled=True):
    plan = Plan(
        name=name,
        price=1000,
        duration_days=30,
        owner_admin_id=owner_admin_id,
        tenant_id=tenant_id,
        enabled=enabled,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def test_reseller_sees_only_own_plans():
    with GetDB() as db:
        a1 = _reseller(db)
        a2 = _reseller(db)
        p1 = _plan(db, f"p-{secrets.token_hex(3)}", owner_admin_id=a1.id)
        _plan(db, f"p-{secrets.token_hex(3)}", owner_admin_id=a2.id)
        pydantic = Admin(username=a1.username, is_sudo=False, role="reseller")
        scoped = get_scoped_plans(db, pydantic)
        assert len(scoped) == 1
        assert scoped[0].id == p1.id


def test_portal_user_gets_reseller_catalog():
    with GetDB() as db:
        admin = _reseller(db)
        plan = _plan(db, f"p-{secrets.token_hex(3)}", owner_admin_id=admin.id)
        user = crud.create_user(
            db,
            UserCreate(
                username=f"u{secrets.token_hex(4)}",
                proxies={ProxyTypes.VMess: {"id": "00000000-0000-0000-0000-000000000099"}},
                status=UserStatus.active,
                inbounds={},
            ),
            admin=admin,
        )
        plans = get_plans_for_user_reseller(db, admin.id)
        assert len(plans) == 1
        assert plans[0].id == plan.id
        assert user.admin_id == admin.id


def test_assert_plan_accessible_blocks_other_reseller():
    with GetDB() as db:
        a1 = _reseller(db)
        a2 = _reseller(db)
        plan = _plan(db, f"p-{secrets.token_hex(3)}", owner_admin_id=a2.id)
        pydantic = Admin(username=a1.username, is_sudo=False, role="reseller")
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException, match="catalog"):
            assert_plan_accessible(db, pydantic, plan)


def test_plan_name_unique_per_scope():
    with GetDB() as db:
        admin = _reseller(db)
        name = f"shared-{secrets.token_hex(3)}"
        _plan(db, name, owner_admin_id=admin.id)
        assert plan_name_taken(db, name, tenant_id=None, owner_admin_id=admin.id)
        other = _reseller(db)
        assert not plan_name_taken(db, name, tenant_id=None, owner_admin_id=other.id)
