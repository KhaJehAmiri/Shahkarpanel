"""Phase 5: sub-resellers, MRR, onboarding."""
import secrets

from passlib.context import CryptContext

from app.billing.mrr import compute_mrr
from app.db import GetDB
from app.db.models import Admin as DBAdmin
from app.models.admin import Admin
from app.tenant.sub_reseller import (
    create_sub_reseller,
    list_children,
    onboarding_status,
)

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


def test_create_sub_reseller():
    with GetDB() as db:
        parent = _parent(db)
        child = create_sub_reseller(
            db, parent, username=f"c{secrets.token_hex(4)}", password="secret",
        )
        assert child.parent_admin_id == parent.id
        assert child.tenant_id == parent.tenant_id
        children = list_children(db, parent.id)
        assert len(children) == 1


def test_mrr_counts_revenue():
    with GetDB() as db:
        admin = _parent(db)
        from app import billing

        billing.add_transaction(db, admin.id, 5000, type="credit")
        billing.add_transaction(db, admin.id, -2000, type="usage_billing")
        mrr = compute_mrr(db, days=30)
        assert mrr["total_revenue"] >= 2000
        assert mrr["active_resellers"] >= 1


def test_onboarding_detects_steps():
    with GetDB() as db:
        parent = _parent(db)
        pydantic = Admin(username=parent.username, is_sudo=False, role="reseller")
        status = onboarding_status(db, pydantic)
        assert "steps" in status
        assert status["steps"]["user"] is False
