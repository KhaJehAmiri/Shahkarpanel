"""Phase 11.3 — node core_kind, node_wireguard config, peer-sync planner."""
import importlib.util
import os
import uuid

from app.db import GetDB, crud
from app.models.node import CoreKind, NodeCreate, NodeModify
from app.wireguard import (
    WGUserPeer,
    build_node_spec,
    build_pubkey_user_map,
    generate_keypair,
    server_interface_address,
)

# The node agent's spec parser is the contract the planner must satisfy.
_spec_path = os.path.join(os.path.dirname(__file__), "..", "node", "wireguard.py")
_spec = importlib.util.spec_from_file_location("node_wireguard", _spec_path)
node_wireguard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(node_wireguard)
WireGuardSpec = node_wireguard.WireGuardSpec


# --------------------------------------------------------------------------- #
# Node.core_kind
# --------------------------------------------------------------------------- #
def test_node_defaults_to_xray_core():
    with GetDB() as db:
        node = crud.create_node(db, NodeCreate(name="wg-default", address="1.2.3.4"))
        assert node.core_kind == "xray"


def test_node_created_as_wireguard():
    with GetDB() as db:
        node = crud.create_node(
            db, NodeCreate(name="wg-node", address="5.6.7.8", core_kind=CoreKind.wireguard)
        )
        assert node.core_kind == "wireguard"
        nid = node.id
    with GetDB() as db:
        assert crud.get_node_by_id(db, nid).core_kind == "wireguard"


def test_update_node_core_kind():
    with GetDB() as db:
        node = crud.create_node(db, NodeCreate(name="wg-switch", address="9.9.9.9"))
        crud.update_node(db, node, NodeModify(core_kind=CoreKind.wireguard))
        assert node.core_kind == "wireguard"


# --------------------------------------------------------------------------- #
# node_wireguard one-to-one config
# --------------------------------------------------------------------------- #
def test_set_and_get_node_wireguard():
    priv, pub = generate_keypair()
    with GetDB() as db:
        node = crud.create_node(
            db, NodeCreate(name="wg-cfg", address="10.0.0.1", core_kind=CoreKind.wireguard)
        )
        crud.set_node_wireguard(
            db, node, interface="wg1", listen_port=51821,
            subnet="10.20.0.0/24", private_key=priv, public_key=pub,
            endpoint="vpn.example.com:51821",
        )
        nid = node.id
    with GetDB() as db:
        node = crud.get_node_by_id(db, nid)
        assert node.wireguard is not None
        assert node.wireguard.interface == "wg1"
        assert node.wireguard.listen_port == 51821
        assert node.wireguard.public_key == pub
        assert node.wireguard.endpoint == "vpn.example.com:51821"


def test_set_node_wireguard_is_idempotent_replace():
    priv, pub = generate_keypair()
    priv2, pub2 = generate_keypair()
    with GetDB() as db:
        node = crud.create_node(
            db, NodeCreate(name="wg-replace", address="10.0.0.2", core_kind=CoreKind.wireguard)
        )
        crud.set_node_wireguard(db, node, private_key=priv, public_key=pub)
        crud.set_node_wireguard(db, node, private_key=priv2, public_key=pub2, listen_port=51999)
        nid = node.id
    with GetDB() as db:
        node = crud.get_node_by_id(db, nid)
        assert node.wireguard.public_key == pub2
        assert node.wireguard.listen_port == 51999


def test_get_wireguard_nodes_filters_by_core_kind():
    with GetDB() as db:
        crud.create_node(db, NodeCreate(name="x-only", address="1.1.1.1"))
        crud.create_node(
            db, NodeCreate(name="wg-listed", address="2.2.2.2", core_kind=CoreKind.wireguard)
        )
        wg_nodes = crud.get_wireguard_nodes(db)
        names = {n.name for n in wg_nodes}
        assert "wg-listed" in names
        assert "x-only" not in names


# --------------------------------------------------------------------------- #
# Sync planner
# --------------------------------------------------------------------------- #
def test_server_interface_address_first_host():
    assert server_interface_address("10.10.0.0/24") == "10.10.0.1/24"
    assert server_interface_address("10.10.0.0/16") == "10.10.0.1/16"


def test_build_node_spec_only_active_peers():
    priv, _ = generate_keypair()
    _, pk1 = generate_keypair()
    _, pk2 = generate_keypair()
    peers = [
        WGUserPeer(user_id=1, public_key=pk1, address="10.10.0.2/32", active=True),
        WGUserPeer(user_id=2, public_key=pk2, address="10.10.0.3/32", active=False),
    ]
    spec = build_node_spec(
        interface="wg0", listen_port=51820, private_key=priv,
        subnet="10.10.0.0/24", peers=peers,
    )
    assert spec["address"] == "10.10.0.1/24"
    assert len(spec["peers"]) == 1
    assert spec["peers"][0]["public_key"] == pk1
    assert spec["peers"][0]["allowed_ips"] == ["10.10.0.2/32"]


def test_build_node_spec_dedups_and_normalizes_allowed_ips():
    priv, _ = generate_keypair()
    _, pk = generate_keypair()
    peers = [
        WGUserPeer(user_id=1, public_key=pk, address="10.10.0.5", active=True),
        WGUserPeer(user_id=1, public_key=pk, address="10.10.0.5", active=True),
    ]
    spec = build_node_spec(
        interface="wg0", listen_port=51820, private_key=priv,
        subnet="10.10.0.0/24", peers=peers, mtu=1400,
    )
    assert len(spec["peers"]) == 1
    assert spec["peers"][0]["allowed_ips"] == ["10.10.0.5/32"]
    assert spec["mtu"] == 1400


def test_build_node_spec_is_consumable_by_node_agent():
    priv, _ = generate_keypair()
    _, pk = generate_keypair()
    spec_dict = build_node_spec(
        interface="wg0", listen_port=51820, private_key=priv,
        subnet="10.10.0.0/24",
        peers=[WGUserPeer(user_id=7, public_key=pk, address="10.10.0.9/32")],
    )
    parsed = WireGuardSpec.from_dict(spec_dict)
    assert parsed.interface == "wg0"
    assert parsed.address == ["10.10.0.1/24"]
    assert parsed.peers[0].public_key == pk
    assert parsed.peers[0].allowed_ips == ["10.10.0.9/32"]


def test_ensure_addresses_allocates_unique_ips():
    from app.db.models import Proxy, User
    from app.models.proxy import ProxyTypes
    from app.models.user import UserStatus
    from app.wireguard.operations import ensure_addresses_for_subnet
    subnet = "10.77.0.0/24"
    with GetDB() as db:
        ids = []
        for _ in range(3):
            priv, pub = generate_keypair()
            u = User(username=f"wga-{uuid.uuid4().hex[:8]}", status=UserStatus.active)
            db.add(u)
            db.commit()
            db.add(Proxy(type=ProxyTypes.WireGuard.value,
                         settings={"private_key": priv, "public_key": pub},
                         user_id=u.id))
            db.commit()
            ids.append(u.id)
        ensure_addresses_for_subnet(db, subnet)
        addrs = [
            db.query(Proxy).filter(Proxy.user_id == i).first().settings.get("address")
            for i in ids
        ]
        assert all(a and a.startswith("10.77.0.") for a in addrs)
        assert len(set(addrs)) == len(addrs)  # unique


def test_pubkey_user_map_includes_inactive_for_trailing_usage():
    _, pk1 = generate_keypair()
    _, pk2 = generate_keypair()
    peers = [
        WGUserPeer(user_id=10, public_key=pk1, address="10.10.0.2/32", active=True),
        WGUserPeer(user_id=20, public_key=pk2, address="10.10.0.3/32", active=False),
    ]
    mapping = build_pubkey_user_map(peers)
    assert mapping == {pk1: 10, pk2: 20}
