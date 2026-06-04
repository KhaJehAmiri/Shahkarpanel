"""Security regressions for phases 13.x (no httpx/TestClient required)."""
import inspect

import pytest

from app import api_keys as api_keys_mod
from app import feature_flags as ff
from app.db import GetDB, crud
from app.db.models import Admin as DBAdmin, ApiKey, JWT
from app.routers import metrics as metrics_router
from app.utils import jwt as jwt_util


def _ensure_jwt_row():
    with GetDB() as db:
        if db.query(JWT).first() is None:
            db.add(JWT(secret_key="test-jwt-secret-key-32-bytes-min!!"))
            db.commit()
    jwt_util.clear_secret_key_cache()


def test_subscription_token_roundtrip():
    _ensure_jwt_row()
    token = jwt_util.create_subscription_token("alice")
    assert len(token) > 20
    payload = jwt_util.get_subscription_payload(token)
    assert payload is not None
    assert payload["username"] == "alice"


def test_metrics_authorize_ignores_query_string():
    assert "query_params" not in inspect.getsource(metrics_router._authorize)


def test_api_key_scope_allow():
    record = ApiKey(admin_id=1, name="t", prefix="abcd", key_hash="x", scopes=["users:read"])
    assert api_keys_mod._scopes_allow(record, "users:read") is True
    assert api_keys_mod._scopes_allow(record, "billing:write") is False
    record.scopes = ["*"]
    assert api_keys_mod._scopes_allow(record, "billing:write") is True


def test_v2_route_uses_scope_dependency():
    from app.routers import v2 as v2_router
    src = inspect.getsource(v2_router.list_users)
    assert "require_v2_scope" in src


def test_reseller_max_users_enforced():
    with GetDB() as db:
        owner = DBAdmin(
            username="owner-quota",
            hashed_password="x",
            is_sudo=False,
            role="reseller",
            max_users=1,
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        from app.models.user import UserCreate, UserStatus
        from app.models.proxy import ProxyTypes

        body = UserCreate(
            username="usr1",
            proxies={ProxyTypes.VMess: {"id": "00000000-0000-0000-0000-000000000001"}},
            status=UserStatus.active,
            inbounds={},
        )
        crud.create_user(db, body, admin=owner)
        with pytest.raises(ValueError, match="limit"):
            crud.create_user(
                db,
                UserCreate(
                    username="usr2",
                    proxies={ProxyTypes.VMess: {"id": "00000000-0000-0000-0000-000000000002"}},
                    status=UserStatus.active,
                    inbounds={},
                ),
                admin=owner,
            )
