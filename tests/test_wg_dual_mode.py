"""Dual-stack WireGuard: plain wg0 + AmneziaWG wg1."""
import uuid

from app.db import GetDB, crud
from app.models.node import CoreKind, NodeCreate
from app.wireguard import generate_keypair
from app.wireguard.sync import amneziawg_enabled, build_node_specs, plain_wg_enabled


def test_build_node_specs_plain_only():
    priv, pub = generate_keypair()
    with GetDB() as db:
        node = crud.create_node(
            db, NodeCreate(name=f"wg-{uuid.uuid4().hex[:6]}", address="1.2.3.4", core_kind=CoreKind.wireguard),
        )
        cfg = crud.provision_wireguard_defaults(db, node, plain_enabled=True, awg_enabled=False)
        from app.wireguard.sync import WGUserPeer
        peers = [WGUserPeer(user_id=1, public_key="PUB", address="10.10.0.2/32")]
        specs = build_node_specs(cfg, peers)
    assert len(specs) == 1
    assert specs[0]["interface"] == "wg0"
    assert specs[0]["listen_port"] == 51820
    assert "amnezia" not in specs[0]


def test_build_node_specs_dual():
    priv, pub = generate_keypair()
    with GetDB() as db:
        node = crud.create_node(
            db, NodeCreate(name=f"wg-{uuid.uuid4().hex[:6]}", address="1.2.3.4", core_kind=CoreKind.wireguard),
        )
        cfg = crud.provision_wireguard_defaults(db, node, plain_enabled=True, awg_enabled=True)
        from app.wireguard.sync import WGUserPeer
        peers = [
            WGUserPeer(user_id=1, public_key="PUB", address="10.10.0.2/32", awg_address="10.11.0.2/32"),
        ]
        specs = build_node_specs(cfg, peers)
    assert len(specs) == 2
    assert specs[0]["listen_port"] == 51820
    assert specs[1]["interface"] == "wg1"
    assert specs[1]["listen_port"] == 51821
    assert specs[1]["amnezia"]["Jc"] is not None


def test_stack_flags():
    priv, pub = generate_keypair()
    with GetDB() as db:
        node = crud.create_node(
            db, NodeCreate(name=f"wg-{uuid.uuid4().hex[:6]}", address="1.2.3.4", core_kind=CoreKind.wireguard),
        )
        cfg = crud.provision_wireguard_defaults(db, node, plain_enabled=True, awg_enabled=True)
        assert plain_wg_enabled(cfg)
        assert amneziawg_enabled(cfg)
