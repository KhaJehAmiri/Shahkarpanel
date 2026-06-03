"""WireGuard product support (Phase 11).

WireGuard is a first-class user protocol served by a native WireGuard interface
on the node, not by Xray. Its traffic is folded into the single
``User.used_traffic`` via the same pipeline as every other protocol — see
``docs/accounting-contract.md``.

This package holds the panel-side primitives:

- ``keys``  — X25519 keypair / preshared-key generation.
- ``pool``  — peer IP allocation within a node's WireGuard subnet.
- ``sync``  — peer-sync planner (node spec + public_key->User.id map).
"""
from app.wireguard.keys import (
    generate_keypair,
    generate_preshared_key,
    public_key_from_private,
)
from app.wireguard.pool import WireGuardPeerIPAllocator
from app.wireguard.sync import (
    WGUserPeer,
    build_node_spec,
    build_pubkey_user_map,
    server_interface_address,
)

__all__ = [
    "generate_keypair",
    "generate_preshared_key",
    "public_key_from_private",
    "WireGuardPeerIPAllocator",
    "WGUserPeer",
    "build_node_spec",
    "build_pubkey_user_map",
    "server_interface_address",
]
