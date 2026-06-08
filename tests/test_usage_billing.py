"""Phase 3: GB usage billing with BYO-node split."""
import secrets
from datetime import datetime, timedelta

from passlib.context import CryptContext

from app.billing.usage_billing import (
    aggregate_reseller_usage,
    align_hour,
    bill_reseller_usage,
    get_or_create_checkpoint,
    node_owned_by_reseller,
    traffic_to_gb_units,
    usage_summary_for_admin,
    wallet_is_low,
)
from app.db import GetDB, crud
from app.db.models import Admin as DBAdmin
from app.db.models import Node, NodeUserUsage
from app.models.proxy import ProxyTypes
from app.models.user import UserCreate, UserStatus

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
GB = 1024 ** 3


def _reseller(db):
    name = f"rs{secrets.token_hex(4)}"
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


def test_traffic_to_gb_units_rounds_up():
    assert traffic_to_gb_units(0) == 0
    assert traffic_to_gb_units(1) == 1
    assert traffic_to_gb_units(GB) == 1
    assert traffic_to_gb_units(GB + 1) == 2


def test_node_ownership_by_owner_admin_id():
    node = Node(owner_admin_id=7, tenant_id=None)
    assert node_owned_by_reseller(node, 7, None)
    assert not node_owned_by_reseller(node, 8, None)


def test_aggregate_splits_owned_and_foreign():
    with GetDB() as db:
        admin = _reseller(db)
        user = _user(db, admin)
        owned = Node(
            name=f"own{secrets.token_hex(3)}",
            address="1.2.3.4",
            port=62050,
            api_port=62051,
            owner_admin_id=admin.id,
        )
        foreign = Node(
            name=f"for{secrets.token_hex(3)}",
            address="5.6.7.8",
            port=62050,
            api_port=62051,
            owner_admin_id=None,
        )
        db.add_all([owned, foreign])
        db.commit()
        hour = align_hour(datetime.utcnow())
        db.add(NodeUserUsage(user_id=user.id, node_id=owned.id, created_at=hour, used_traffic=2 * GB))
        db.add(NodeUserUsage(user_id=user.id, node_id=foreign.id, created_at=hour, used_traffic=GB))
        db.commit()

        since = hour - timedelta(hours=1)
        split = aggregate_reseller_usage(db, admin.id, None, since, hour)
        assert split.owned_bytes == 2 * GB
        assert split.foreign_bytes == GB


def test_bill_reseller_debits_wallet():
    with GetDB() as db:
        admin = _reseller(db)
        user = _user(db, admin)
        node = Node(
            name=f"n{secrets.token_hex(3)}",
            address="1.2.3.4",
            port=62050,
            api_port=62051,
            owner_admin_id=admin.id,
        )
        db.add(node)
        db.commit()
        hour = align_hour(datetime.utcnow())
        db.add(NodeUserUsage(user_id=user.id, node_id=node.id, created_at=hour, used_traffic=GB))
        db.commit()

        from app import billing

        billing.add_transaction(db, admin.id, 50000, type="credit")
        checkpoint = get_or_create_checkpoint(db, admin.id)
        checkpoint.last_billed_at = hour - timedelta(hours=1)
        db.commit()

        tx, split = bill_reseller_usage(db, admin, rate_per_gb=1000, now=hour + timedelta(minutes=5))
        assert tx is not None
        assert tx.amount == -1000
        assert split.owned_gb == 1
        wallet = billing.get_or_create_wallet(db, admin.id)
        assert wallet.balance == 49000


def test_usage_summary_flags_low_wallet():
    with GetDB() as db:
        admin = _reseller(db)
        from app import billing

        billing.add_transaction(db, admin.id, 500, type="credit")
        summary = usage_summary_for_admin(db, admin, rate_per_gb=100)
        assert summary["wallet_low"] is True
        assert wallet_is_low(500) is True
