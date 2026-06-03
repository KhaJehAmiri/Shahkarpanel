"""Phase 11.5 — WireGuard .conf subscription export + quota/status gating."""
import uuid

import pytest
from fastapi import HTTPException

from app.db import GetDB, crud
from app.db.models import Proxy, User
from app.models.node import CoreKind, NodeCreate
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.routers.subscription import user_subscription_wireguard
from app.subscription.wireguard import node_endpoint, render_wireguard_conf, user_config
from app.wireguard import generate_keypair


# --------------------------------------------------------------------------- #
# Pure renderer
# --------------------------------------------------------------------------- #
def test_render_minimal_conf():
    conf = render_wireguard_conf(
        private_key="PRIV", address="10.10.0.2/32",
        server_public_key="SRVPUB", endpoint="vpn.example.com:51820",
    )
    assert "[Interface]" in conf
    assert "PrivateKey = PRIV" in conf
    assert "Address = 10.10.0.2/32" in conf
    assert "[Peer]" in conf
    assert "PublicKey = SRVPUB" in conf
    assert "Endpoint = vpn.example.com:51820" in conf
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in conf
    assert "PersistentKeepalive = 25" in conf


def test_render_optional_fields():
    conf = render_wireguard_conf(
        private_key="P", address="10.0.0.2/32", server_public_key="S",
        endpoint="h:1", dns="1.1.1.1", preshared_key="PSK", mtu=1420,
    )
    assert "DNS = 1.1.1.1" in conf
    assert "PresharedKey = PSK" in conf
    assert "MTU = 1420" in conf


# --------------------------------------------------------------------------- #
# node_endpoint / user_config
# --------------------------------------------------------------------------- #
class _Cfg:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Node:
    def __init__(self, address, wg):
        self.address = address
        self.name = "wgnode"
        self.wireguard = wg


def test_node_endpoint_prefers_explicit():
    node = _Node("1.2.3.4", _Cfg(endpoint="vpn:9999", listen_port=51820))
    assert node_endpoint(node) == "vpn:9999"


def test_node_endpoint_derived_from_address():
    node = _Node("1.2.3.4", _Cfg(endpoint=None, listen_port=51820))
    assert node_endpoint(node) == "1.2.3.4:51820"


def test_user_config_none_without_address():
    node = _Node("1.2.3.4", _Cfg(endpoint=None, listen_port=51820, public_key="S", dns=None, mtu=1420))
    assert user_config({"private_key": "P"}, node) is None  # no address


def test_user_config_builds_conf():
    node = _Node("1.2.3.4", _Cfg(endpoint=None, listen_port=51820, public_key="SRV", dns="8.8.8.8", mtu=1420))
    conf = user_config({"private_key": "P", "address": "10.0.0.5/32", "preshared_key": "K"}, node)
    assert "Endpoint = 1.2.3.4:51820" in conf
    assert "PublicKey = SRV" in conf
    assert "PresharedKey = K" in conf


# --------------------------------------------------------------------------- #
# Endpoint: status / quota gating
# --------------------------------------------------------------------------- #
def _mk_user_with_wg(db, status=UserStatus.active, data_limit=None, used=0, with_wg=True):
    priv, pub = generate_keypair()
    u = User(username=f"wg-{uuid.uuid4().hex[:8]}", status=status,
             data_limit=data_limit, used_traffic=used)
    db.add(u)
    db.commit()
    if with_wg:
        db.add(Proxy(type=ProxyTypes.WireGuard.value,
                     settings={"private_key": priv, "public_key": pub, "address": "10.10.0.2/32"},
                     user_id=u.id))
        db.commit()
    return u


def _mk_wg_node(db):
    priv, pub = generate_keypair()
    node = crud.create_node(
        db, NodeCreate(name=f"wg-{uuid.uuid4().hex[:6]}", address="5.5.5.5",
                       core_kind=CoreKind.wireguard))
    crud.set_node_wireguard(db, node, private_key=priv, public_key=pub,
                            endpoint="vpn.example.com:51820")
    return node


def test_endpoint_returns_conf_for_active_user():
    with GetDB() as db:
        user = _mk_user_with_wg(db, UserStatus.active)
        node = _mk_wg_node(db)
        resp = user_subscription_wireguard(dbuser=user, node_id=node.id, db=db)
        body = resp.body.decode()
        assert resp.status_code == 200
        assert "[Interface]" in body
        assert "Endpoint = vpn.example.com:51820" in body


def test_endpoint_lazily_allocates_address_when_missing():
    from app.db.models import Proxy
    from app.wireguard import generate_keypair
    with GetDB() as db:
        # user with a WG proxy but NO address
        priv, pub = generate_keypair()
        u = User(username=f"wg-{uuid.uuid4().hex[:8]}", status=UserStatus.active)
        db.add(u)
        db.commit()
        db.add(Proxy(type=ProxyTypes.WireGuard.value,
                     settings={"private_key": priv, "public_key": pub},
                     user_id=u.id))
        db.commit()
        node = _mk_wg_node(db)
        resp = user_subscription_wireguard(dbuser=u, node_id=node.id, db=db)
        assert resp.status_code == 200
        assert "Address = " in resp.body.decode()
        # address persisted on the proxy
        proxy = db.query(Proxy).filter(Proxy.user_id == u.id).first()
        assert proxy.settings.get("address")


def test_endpoint_403_for_disabled_user():
    with GetDB() as db:
        user = _mk_user_with_wg(db, UserStatus.disabled)
        _mk_wg_node(db)
        with pytest.raises(HTTPException) as exc:
            user_subscription_wireguard(dbuser=user, node_id=None, db=db)
        assert exc.value.status_code == 403


def test_endpoint_403_when_over_quota():
    with GetDB() as db:
        user = _mk_user_with_wg(db, UserStatus.active, data_limit=1000, used=1000)
        _mk_wg_node(db)
        with pytest.raises(HTTPException) as exc:
            user_subscription_wireguard(dbuser=user, node_id=None, db=db)
        assert exc.value.status_code == 403


def test_endpoint_404_when_user_has_no_wireguard():
    with GetDB() as db:
        user = _mk_user_with_wg(db, UserStatus.active, with_wg=False)
        _mk_wg_node(db)
        with pytest.raises(HTTPException) as exc:
            user_subscription_wireguard(dbuser=user, node_id=None, db=db)
        assert exc.value.status_code == 404


def test_endpoint_404_when_node_not_found():
    with GetDB() as db:
        user = _mk_user_with_wg(db, UserStatus.active)
        with pytest.raises(HTTPException) as exc:
            user_subscription_wireguard(dbuser=user, node_id=999999, db=db)
        assert exc.value.status_code == 404
