"""Reseller workspace: scoped nodes, limits, KPIs."""
import secrets

from passlib.context import CryptContext

from app.db import GetDB, crud
from app.db.models import Admin as DBAdmin
from app.db.models import Node
from app.tenant.reseller_ops import (
    assert_can_add_node,
    count_owned_nodes,
    list_scoped_nodes,
    resolve_max_nodes,
    workspace_summary,
)

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _reseller(db, max_nodes=2):
    name = f"rs-{secrets.token_hex(3)}"
    admin = DBAdmin(
        username=name,
        hashed_password=pwd.hash("x"),
        is_sudo=False,
        role="reseller",
        max_nodes=max_nodes,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def test_scoped_nodes_by_owner():
    with GetDB() as db:
        admin = _reseller(db)
        db.add(Node(name=f"n-{secrets.token_hex(3)}", address="1.2.3.4", port=62050, api_port=62051, owner_admin_id=admin.id))
        db.add(Node(name=f"n-{secrets.token_hex(3)}", address="5.6.7.8", port=62050, api_port=62051, owner_admin_id=None))
        db.commit()
        from app.models.admin import Admin
        pydantic = Admin(username=admin.username, is_sudo=False, role="reseller")
        owned = list_scoped_nodes(db, pydantic)
        assert len(owned) == 1
        assert owned[0].owner_admin_id == admin.id


def test_node_limit_enforced():
    with GetDB() as db:
        admin = _reseller(db, max_nodes=1)
        db.add(Node(name=f"n-{secrets.token_hex(3)}", address="1.2.3.4", port=62050, api_port=62051, owner_admin_id=admin.id))
        db.commit()
        from app.models.admin import Admin
        from fastapi import HTTPException
        import pytest
        pydantic = Admin(username=admin.username, is_sudo=False, role="reseller", max_nodes=1)
        with pytest.raises(HTTPException, match="limit"):
            assert_can_add_node(db, pydantic)


def test_workspace_summary_counts():
    with GetDB() as db:
        admin = _reseller(db, max_nodes=5)
        from app.models.admin import Admin
        pydantic = Admin(username=admin.username, is_sudo=False, role="reseller", max_nodes=5)
        ws = workspace_summary(db, pydantic)
        assert ws["username"] == admin.username
        assert ws["max_nodes"] == 5
        assert ws["nodes_count"] == count_owned_nodes(db, admin, None)
