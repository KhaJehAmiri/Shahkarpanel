"""Integration tests for SigmaGuard Client API (direct router calls)."""
import secrets

from passlib.context import CryptContext

from app import feature_flags
from app.db import GetDB, crud
from app.db.models import Admin as DBAdmin
from app.models.proxy import ProxyTypes
from app.models.user import UserCreate, UserModify, UserStatus
from app.routers.client_v2 import client_config, client_negotiate
from app.utils.jwt import clear_secret_key_cache

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _jwt_ready(db):
    from app.db.crud import get_jwt_secret_key
    from app.db.models import JWT

    if not db.query(JWT).first():
        db.add(JWT(secret_key=secrets.token_hex(32)))
        db.commit()
    get_jwt_secret_key(db)
    clear_secret_key_cache()


def _reseller(db):
    admin = DBAdmin(
        username=f"r-{secrets.token_hex(4)}",
        hashed_password=pwd.hash("x"),
        is_sudo=False,
        role="reseller",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _portal_user(db, admin, username=None):
    username = username or f"app-{secrets.token_hex(4)}"
    user = crud.create_user(
        db,
        UserCreate(
            username=username,
            proxies={ProxyTypes.VMess: {"id": "00000000-0000-0000-0000-000000000088"}},
            status=UserStatus.active,
            inbounds={},
            data_limit=0,
        ),
        admin=admin,
    )
    crud.update_user(
        db,
        user,
        UserModify(portal_enabled=True, portal_password="appsecret1"),
    )
    db.refresh(user)
    return user


def test_client_config_integration():
    feature_flags.set_flag("client_api", True)
    try:
        with GetDB() as db:
            _jwt_ready(db)
            user = _portal_user(db, _reseller(db))
            resp = client_config(
                profile=None,
                net="open",
                udp=True,
                country="IR",
                db=db,
                dbuser=user,
            )
        assert resp.profile in ("gamer", "trader", "normal")
        assert isinstance(resp.protocol_materials, dict)
        assert resp.tunnel.topology in ("direct", "relay_exit")
        assert len(resp.protocols) >= 1
        proto_names = {p.protocol for p in resp.protocols}
        assert proto_names  # non-empty when xray serves vless
    finally:
        feature_flags.set_flag("client_api", False)
        feature_flags.invalidate_cache()


def test_client_negotiate_integration():
    feature_flags.set_flag("client_api", True)
    try:
        with GetDB() as db:
            user = _portal_user(db, _reseller(db))
            resp = client_negotiate(
                profile="gamer",
                net="open",
                udp=True,
                db=db,
                dbuser=user,
            )
        assert resp.profile == "gamer"
        assert "tuic" not in resp.usable_protocols[:3]
    finally:
        feature_flags.set_flag("client_api", False)
        feature_flags.invalidate_cache()


def test_ensure_app_proxies_adds_required_types():
    from app.client.provision import ensure_app_proxies, required_app_proxy_types

    with GetDB() as db:
        admin = _reseller(db)
        user = crud.create_user(
            db,
            UserCreate(
                username=f"thin-{secrets.token_hex(4)}",
                proxies={ProxyTypes.VMess: {"id": "00000000-0000-0000-0000-000000000099"}},
                status=UserStatus.active,
                inbounds={},
                data_limit=0,
            ),
            admin=admin,
        )
        user.portal_enabled = True
        db.commit()
        assert ensure_app_proxies(db, user) is True
        db.refresh(user)
        types = {ProxyTypes(p.type) for p in user.proxies}
        for pt in required_app_proxy_types():
            assert pt in types


def test_gamer_rank_prefers_country_region():
    from app import client as engine

    nodes = [
        {"id": 1, "name": "us", "region": "na", "address": "a", "latency_ms": 20.0},
        {"id": 2, "name": "ir", "region": "iran", "address": "b", "latency_ms": 80.0},
    ]
    ranked = engine.rank_nodes(nodes, country="IR")
    assert ranked[0]["id"] == 2
