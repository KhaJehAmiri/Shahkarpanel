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
    speed_limit_up: Optional[int] = None
    speed_limit_down: Optional[int] = None
    username: str = ""                # for Xray stats email attribution (see xray_native.py)
    finalmask_slot: int = 0           # sticky Finalmask shard (app/wireguard/finalmask_shard.py)


def server_interface_address(
    subnet: str,
    *,
    interface_host: Optional[str] = None,
) -> str:
    """The node interface address carrying the subnet prefix.

    Prefer ``interface_host`` when set (historical gateway after a non-aligned
    widen). e.g. ``"10.10.0.0/24" -> "10.10.0.1/24"``;
    ``"10.10.4.0/23", interface_host="10.10.5.1" -> "10.10.5.1/23"``.
    """
    from app.wireguard.capacity import resolve_interface_host

    network = ipaddress.ip_network(subnet, strict=False)
    server = resolve_interface_host(subnet, interface_host)
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


def sg_wire_enabled(cfg) -> bool:
    """True when this node serves the proprietary SigmaGuard Wire preset."""
    if cfg is None:
        return False
    return bool(getattr(cfg, "sg_wire_enabled", False))


def direct_wg_enabled(cfg) -> bool:
    """True when a parallel, untunneled plain-WG socket should stay up.

    This is the same identity (keys/peers/subnet) as the plain listener, just
    bound to a second port so it survives tunnel delegation on relay nodes —
    lets any stock WireGuard client connect directly, alongside the tunneled
    path, without a port conflict.
    """
    if cfg is None:
        return False
    return bool(getattr(cfg, "direct_listen_port", None))


def direct_interface_name(cfg) -> str:
    """Kernel interface name for the direct listener, derived from ``interface``."""
    base = getattr(cfg, "interface", None) or "wg0"
    return f"{base}d"


def awg_params_from_cfg(cfg) -> dict:
    """Extract AmneziaWG [Interface] params from a NodeWireGuard row."""
    mapping = {
        "Jc": getattr(cfg, "awg_jc", None),
        "Jmin": getattr(cfg, "awg_jmin", None),
        "Jmax": getattr(cfg, "awg_jmax", None),
        "S1": getattr(cfg, "awg_s1", None),
        "S2": getattr(cfg, "awg_s2", None),
        "S3": getattr(cfg, "awg_s3", None),
        "S4": getattr(cfg, "awg_s4", None),
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
    interface_host: Optional[str] = None,
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
        if not p.address:
            # A peer with no address for this variant (e.g. a plain-WG-only
            # user on the AWG interface) would otherwise render as an empty
            # `AllowedIPs = ` line. `wg`/`awg syncconf` treats the whole
            # config as one atomic transaction and rejects it outright on
            # any unparsable line, wiping *every* peer on the interface —
            # not just the bad one. Skip it instead of shipping a broken
            # entry (see AUDIT_FINDINGS.md C5 incident notes).
            continue
        seen.add(p.public_key)
        peer_payload.append(
            {
                "public_key": p.public_key,
                "allowed_ips": [_normalize_allowed(p.address)] if p.address else [],
                "preshared_key": p.preshared_key or None,
                "speed_limit_up": p.speed_limit_up,
                "speed_limit_down": p.speed_limit_down,
            }
        )
    spec = {
        "interface": interface,
        "listen_port": int(listen_port),
        "private_key": private_key,
        "address": server_interface_address(subnet, interface_host=interface_host),
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
                interface_host=getattr(cfg, "interface_host", None),
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
                speed_limit_up=p.speed_limit_up,
                speed_limit_down=p.speed_limit_down,
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
                interface_host=getattr(cfg, "awg_interface_host", None),
            )
        )
    return specs


def build_direct_spec(cfg, peers: List[WGUserPeer]) -> Optional[dict]:
    """Spec for the parallel direct (untunneled) plain-WG listener, if enabled."""
    if not direct_wg_enabled(cfg):
        return None
    return build_node_spec(
        interface=direct_interface_name(cfg),
        listen_port=cfg.direct_listen_port,
        private_key=cfg.private_key,
        subnet=cfg.subnet,
        peers=peers,
        mtu=cfg.mtu,
        amnezia=None,
        interface_host=getattr(cfg, "interface_host", None),
    )


def build_pubkey_user_map(peers: List[WGUserPeer]) -> Dict[str, int]:
    """Map ``public_key -> User.id`` for folding transfer counters into the
    central ``used_traffic``. Includes every peer with a key (even inactive
    ones) so trailing usage is still attributed to the right user."""
    mapping: Dict[str, int] = {}
    for p in peers:
        if p.public_key:
            mapping[p.public_key] = p.user_id
    return mapping
