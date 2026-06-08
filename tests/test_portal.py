"""End-user portal: auth, renewal, plan application."""
import secrets

from passlib.context import CryptContext

from app.db import GetDB, crud
from app.db.models import Admin as DBAdmin
from app.db.models import Plan, User as DBUser
from app.models.proxy import ProxyTypes
from app.models.user import UserCreate, UserStatus
from app.portal import apply_plan_to_user, compute_renewal_expire
from app.utils.jwt import create_portal_token, get_portal_payload

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _make_reseller(db, username=None):
    username = username or f"reseller-{secrets.token_hex(4)}"
    admin = DBAdmin(
        username=username,
        hashed_password=pwd.hash("x"),
        is_sudo=False,
        role="reseller",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _make_user(db, admin, username=None):
    username = username or f"user-{secrets.token_hex(4)}"
    body = UserCreate(
        username=username,
        proxies={ProxyTypes.VMess: {"id": "00000000-0000-0000-0000-000000000099"}},
        status=UserStatus.active,
        inbounds={},
        data_limit=1024 * 1024,
        expire=1000000000,
    )
    return crud.create_user(db, body, admin=admin)


def test_portal_jwt_roundtrip():
    with GetDB() as db:
        from app.db.crud import get_jwt_secret_key
        from app.db.models import JWT

        if not db.query(JWT).first():
            db.add(JWT(secret_key=secrets.token_hex(32)))
            db.commit()
        get_jwt_secret_key(db)
    from app.utils.jwt import clear_secret_key_cache
    clear_secret_key_cache()
    token = create_portal_token("alice")
    payload = get_portal_payload(token)
    assert payload is not None
    assert payload["username"] == "alice"


def test_verify_portal_user():
    with GetDB() as db:
        admin = _make_reseller(db)
        user = _make_user(db, admin)
        user.portal_enabled = True
        user.hashed_portal_password = pwd.hash("secret123")
        db.commit()
        assert crud.verify_portal_user(db, user.username, "secret123") is not None
        assert crud.verify_portal_user(db, user.username, "wrong") is None
        user.portal_enabled = False
        db.commit()
        assert crud.verify_portal_user(db, user.username, "secret123") is None


def test_apply_plan_extends_user():
    with GetDB() as db:
        admin = _make_reseller(db)
        user = _make_user(db, admin)
        plan = Plan(
            name=f"plan-{secrets.token_hex(4)}",
            price=1000,
            data_limit=2 * 1024 ** 3,
            duration_days=30,
            enabled=True,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        old_expire = user.expire
        user = apply_plan_to_user(db, user, plan)
        assert user.data_limit == plan.data_limit
        assert user.used_traffic == 0
        assert user.expire is not None
        if old_expire:
            assert user.expire >= old_expire
        new_expire = compute_renewal_expire(user, plan)
        assert new_expire is not None
