"""User create API supports all protocol types + portal on create."""
from app.db import GetDB, crud
from app.models.proxy import ProxyTypes
from app.models.user import UserCreate, UserStatus


def test_create_user_hysteria2_and_portal():
    with GetDB() as db:
        user = crud.create_user(
            db,
            UserCreate(
                username="fullcreate1",
                proxies={ProxyTypes.Hysteria2: {}},
                inbounds={ProxyTypes.Hysteria2: []},
                status=UserStatus.active,
                portal_enabled=True,
                portal_password="portal1",
                client_profile="gamer",
            ),
        )
        assert user.portal_enabled is True
        assert user.hashed_portal_password
        assert any(p.type == ProxyTypes.Hysteria2 for p in user.proxies)
