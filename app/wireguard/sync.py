"""Panel-side WireGuard peer-sync planner (Phase 11.3).

Pure functions that turn the panel's view of a WireGuard node (its server
config plus the users that hold a WireGuard proxy) into the declarative spec
consumed by the node agent's ``/wg/apply`` endpoint, and into the
``public_key -> User.id`` map that lets transfer counters fold into the single
central ``User.used_traffic`` (see ``docs/accounting-contract.md``).

No I/O, no DB, no transport here — callers gather the inputs and ship the
result. This keeps the accounting-critical mapping deterministic and unit
testable.
"""
import ipaddress
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class WGUserPeer:
    """A single user's WireGuard identity on a node."""

    user_id: int
    public_key: str
    address: str                      # plain WG subnet address
    preshared_key: Optional[str] = None
    active: bool = True
    awg_address: str = ""             # AmneziaWG subnet address (dual-stack nodes)


def server_interface_address(subnet: str) -> str:
    """The node interface address: first usable host carrying the subnet prefix.

    e.g. ``"10.10.0.0/24" -> "10.10.0.1/24"``.
    """
    network = ipaddress.ip_network(subnet, strict=False)
    server = next(network.hosts(), None)
    if server is None:
        raise ValueError(f"subnet {subnet!r} has no usable host address")
    return f"{server}/{network.prefixlen}"


def _normalize_allowed(address: str) -> str:
    """Coerce a stored peer address to a host route (``/32`` or ``/128``)."""
    raw = address.split("/")[0]
    ip = ipaddress.ip_address(raw)
    prefix = 32 if ip.version == 4 else 128
    return f"{ip}/{prefix}"


def plain_wg_enabled(cfg) -> bool:
    if cfg is None:
        return False
    return bool(getattr(cfg, "plain_enabled", True))


def amneziawg_enabled(cfg) -> bool:
    """True when the AmneziaWG listener is enabled on this node."""
    if cfg is None:
        return False
    return bool(getattr(cfg, "awg_enabled", False))


def awg_params_from_cfg(cfg) -> dict:
    """Extract AmneziaWG [Interface] params from a NodeWireGuard row."""
    mapping = {
        "Jc": getattr(cfg, "awg_jc", None),
        "Jmin": getattr(cfg, "awg_jmin", None),
        "Jmax": getattr(cfg, "awg_jmax", None),
        "S1": getattr(cfg, "awg_s1", None),
        "S2": getattr(cfg, "awg_s2", None),
        "H1": getattr(cfg, "awg_h1", None),
        "H2": getattr(cfg, "awg_h2", None),
        "H3": getattr(cfg, "awg_h3", None),
        "H4": getattr(cfg, "awg_h4", None),
    }
    return {k: int(v) for k, v in mapping.items() if v is not None}


def build_node_spec(
    *,
    interface: str,
    listen_port: int,
    private_key: str,
    subnet: str,
    peers: List[WGUserPeer],
    mtu: Optional[int] = None,
    amnezia: Optional[dict] = None,
) -> dict:
    """Build the declarative spec dict for the node agent's ``/wg/apply``.

    Only ``active`` peers with a public key are included — disabled/limited/
    expired users are dropped so they stop carrying traffic immediately.
    """
    peer_payload = []
    seen = set()
    for p in peers:
        if not p.active or not p.public_key or p.public_key in seen:
            continue
        seen.add(p.public_key)
        peer_payload.append(
            {
                "public_key": p.public_key,
                "allowed_ips": [_normalize_allowed(p.address)] if p.address else [],
                "preshared_key": p.preshared_key or None,
            }
        )
    spec = {
        "interface": interface,
        "listen_port": int(listen_port),
        "private_key": private_key,
        "address": server_interface_address(subnet),
        "peers": peer_payload,
        "mtu": int(mtu) if mtu else None,
    }
    if amnezia:
        spec["amnezia"] = amnezia
    return spec


def build_node_specs(cfg, peers: List[WGUserPeer]) -> List[dict]:
    """Build zero, one, or two specs for dual-stack WG nodes."""
    if cfg is None:
        return []
    specs: List[dict] = []
    if plain_wg_enabled(cfg):
        specs.append(
            build_node_spec(
                interface=cfg.interface,
                listen_port=cfg.listen_port,
                private_key=cfg.private_key,
                subnet=cfg.subnet,
                peers=peers,
                mtu=cfg.mtu,
                amnezia=None,
            )
        )
    if amneziawg_enabled(cfg):
        awg_peers = [
            WGUserPeer(
                user_id=p.user_id,
                public_key=p.public_key,
                address=p.awg_address or "",
                preshared_key=p.preshared_key,
                active=p.active,
            )
            for p in peers
        ]
        if not cfg.awg_private_key or not cfg.awg_public_key:
            raise ValueError("AmneziaWG enabled but server keys are missing")
        from app.wireguard.awg import AWG_RECOMMENDED_MTU

        specs.append(
            build_node_spec(
                interface=cfg.awg_interface,
                listen_port=cfg.awg_listen_port,
                private_key=cfg.awg_private_key,
                subnet=cfg.awg_subnet,
                peers=awg_peers,
                mtu=AWG_RECOMMENDED_MTU,
                amnezia=awg_params_from_cfg(cfg) or None,
            )
        )
    return specs


def build_pubkey_user_map(peers: List[WGUserPeer]) -> Dict[str, int]:
    """Map ``public_key -> User.id`` for folding transfer counters into the
    central ``used_traffic``. Includes every peer with a key (even inactive
    ones) so trailing usage is still attributed to the right user."""
    mapping: Dict[str, int] = {}
    for p in peers:
        if p.public_key:
            mapping[p.public_key] = p.user_id
    return mapping
