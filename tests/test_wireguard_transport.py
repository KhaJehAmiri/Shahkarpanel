"""Phase 11.3 — WireGuard panel->node transport + sync orchestration."""
import uuid

from app.db import GetDB, crud
from app.db.models import Proxy, User
from app.models.node import CoreKind, NodeCreate
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.wireguard import generate_keypair
from app.wireguard import operations as wg_ops
from app.wireguard.transport import (
    RESTWireGuardClient,
    RPyCWireGuardClient,
    client_for_node,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeRestNode:
    def __init__(self):
        self.calls = []
        self.connected = True

    def make_request(self, path, timeout, **params):
        self.calls.append((path, params))
        if path == "/wg/transfer":
            return {"transfer": {"PUBKEY": {"rx": 10, "tx": 20}}}
        return {}


class _Remote:
    def __init__(self):
        self.calls = []

    def wg_apply(self, spec):
        self.calls.append(("apply", spec))

    def wg_apply_json(self, spec_json):
        import json
        self.calls.append(("apply_json", json.loads(spec_json)))

    def wg_transfer(self, interface):
        self.calls.append(("transfer", interface))
        return {"PUBKEY": {"rx": 1, "tx": 2}}

    def wg_down(self, interface):
        self.calls.append(("down", interface))


class FakeRpycNode:
    def __init__(self):
        self.remote = _Remote()
        self.connected = True


# --------------------------------------------------------------------------- #
# Transport detection
# --------------------------------------------------------------------------- #
def test_client_for_node_detects_rest():
    assert isinstance(client_for_node(FakeRestNode()), RESTWireGuardClient)


def test_client_for_node_detects_rpyc():
    assert isinstance(client_for_node(FakeRpycNode()), RPyCWireGuardClient)


def test_client_for_node_none_for_unknown_or_none():
    assert client_for_node(None) is None
    assert client_for_node(object()) is None


def test_rest_client_apply_and_transfer():
    node = FakeRestNode()
    client = RESTWireGuardClient(node)
    client.apply({"interface": "wg0"})
    client.transfer("wg0")
    assert node.calls[0][0] == "/wg/apply"
    assert node.calls[0][1] == {"spec": {"interface": "wg0"}}
    assert client.transfer("wg0") == {"PUBKEY": {"rx": 10, "tx": 20}}


def test_rpyc_client_apply_and_transfer():
    node = FakeRpycNode()
    client = RPyCWireGuardClient(node)
    client.apply({"interface": "wg0"})
    assert node.remote.calls[0] == ("apply_json", {"interface": "wg0"})
    assert client.transfer("wg0") == {"PUBKEY": {"rx": 1, "tx": 2}}


def test_rpyc_client_apply_sends_plain_dict_tree():
    """Nested spec must survive JSON round-trip (RPyC netref workaround)."""
    node = FakeRpycNode()
    client = RPyCWireGuardClient(node)
    spec = {
        "interface": "wg0",
        "listen_port": 51820,
        "private_key": "priv",
        "address": "10.10.0.1/24",
        "peers": [{"public_key": "PUB", "allowed_ips": ["10.10.0.2/32"]}],
    }
    client.apply(spec)
    sent = node.remote.calls[0][1]  # apply_json → parsed dict
    assert isinstance(sent, dict)
    assert sent["peers"][0]["allowed_ips"] == ["10.10.0.2/32"]


# --------------------------------------------------------------------------- #
# Peer collection
# --------------------------------------------------------------------------- #
def _mk_wg_user(db, status=UserStatus.active):
    priv, pub = generate_keypair()
    u = User(username=f"wg-{uuid.uuid4().hex[:8]}", status=status)
    db.add(u)
    db.commit()
    db.add(Proxy(type=ProxyTypes.WireGuard.value,
                 settings={"private_key": priv, "public_key": pub,
                           "address": "10.10.0.2/32"},
                 user_id=u.id))
    db.commit()
    return u.id, pub


def test_collect_wg_peers_marks_active_vs_disabled():
    with GetDB() as db:
        active_id, active_pk = _mk_wg_user(db, UserStatus.active)
        disabled_id, disabled_pk = _mk_wg_user(db, UserStatus.disabled)
        peers = {p.public_key: p for p in wg_ops.collect_wg_peers(db)}
        assert peers[active_pk].active is True
        assert peers[active_pk].user_id == active_id
        assert peers[disabled_pk].active is False


# --------------------------------------------------------------------------- #
# sync_node / sync_all_nodes
# --------------------------------------------------------------------------- #
def test_sync_node_pushes_spec_to_client():
    priv, pub = generate_keypair()
    node = FakeRestNode()
    with GetDB() as db:
        dbnode = crud.create_node(
            db, NodeCreate(name=f"wg-{uuid.uuid4().hex[:6]}", address="1.2.3.4",
                           core_kind=CoreKind.wireguard))
        crud.set_node_wireguard(db, dbnode, interface="wg0", listen_port=51820,
                                subnet="10.10.0.0/24", private_key=priv, public_key=pub)
        _mk_wg_user(db, UserStatus.active)
        ok = wg_ops.sync_node(db, dbnode, node_object=node)
    assert ok is True
    path, params = node.calls[0]
    assert path == "/wg/apply"
    spec = params["spec"]
    assert spec["interface"] == "wg0"
    assert spec["address"] == "10.10.0.1/24"
    assert len(spec["peers"]) >= 1


def test_sync_node_false_when_no_wg_config():
    node = FakeRestNode()
    with GetDB() as db:
        dbnode = crud.create_node(
            db, NodeCreate(name=f"x-{uuid.uuid4().hex[:6]}", address="9.9.9.9"))
        assert wg_ops.sync_node(db, dbnode, node_object=node) is False


def test_sync_node_false_when_node_disconnected():
    priv, pub = generate_keypair()
    with GetDB() as db:
        dbnode = crud.create_node(
            db, NodeCreate(name=f"wg-{uuid.uuid4().hex[:6]}", address="1.1.1.1",
                           core_kind=CoreKind.wireguard))
        crud.set_node_wireguard(db, dbnode, private_key=priv, public_key=pub)
        assert wg_ops.sync_node(db, dbnode, node_object=None) is False


def test_sync_all_nodes_counts_successful(monkeypatch):
    priv, pub = generate_keypair()
    node = FakeRestNode()
    with GetDB() as db:
        dbnode = crud.create_node(
            db, NodeCreate(name=f"wg-{uuid.uuid4().hex[:6]}", address="2.2.2.2",
                           core_kind=CoreKind.wireguard))
        crud.set_node_wireguard(db, dbnode, private_key=priv, public_key=pub)
        target_id = dbnode.id

        monkeypatch.setattr(
            wg_ops, "_node_object",
            lambda node_id: node if node_id == target_id else None,
        )
        assert wg_ops.sync_all_nodes(db) >= 1
