"""Shared helpers for relay nodes that delegate egress to a tunnel."""
import logging
import time
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Set

from app import tunnel as tunnel_svc
from app.db import crud
from app.wireguard.sync import plain_wg_enabled

logger = logging.getLogger("nexus-tunnel")

_RELAY_INDEX_TTL_SEC = 30.0
_relay_index_cache: Optional["TunnelRelayIndex"] = None
_relay_index_at: float = 0.0
_pubkey_mismatch_logged: Set[int] = set()


@dataclass(frozen=True)
class TunnelRelayIndex:
    delegate_port_by_relay: Dict[int, int]
    panel_exit_relays: FrozenSet[int]
    canonical_pubkey: Optional[str]
    relay_pubkey_by_node: Dict[int, str]


def clear_tunnel_relay_cache() -> None:
    global _relay_index_cache, _relay_index_at
    _relay_index_cache = None
    _relay_index_at = 0.0
    _pubkey_mismatch_logged.clear()


def _tunnel_relay_index(db) -> TunnelRelayIndex:
    global _relay_index_cache, _relay_index_at

    now = time.monotonic()
    if _relay_index_cache is not None and now - _relay_index_at < _RELAY_INDEX_TTL_SEC:
        return _relay_index_cache

    from app.db.models import Node, Tunnel

    delegate_port_by_relay: Dict[int, int] = {}
    panel_exit_relays: set[int] = set()
    canonical_pubkey: Optional[str] = None
    canonical_tunnel_id: Optional[int] = None
    relay_pubkey_by_node: Dict[int, str] = {}

    tunnels = db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all()
    node_ids: set[int] = set()
    for t in tunnels:
        if t.relay_node_id is not None:
            node_ids.add(int(t.relay_node_id))

    if node_ids:
        for node in db.query(Node).filter(Node.id.in_(sorted(node_ids))).all():
            cfg = node.wireguard
            if cfg is not None and getattr(cfg, "public_key", None):
                relay_pubkey_by_node[int(node.id)] = str(cfg.public_key)

    for t in sorted(tunnels, key=lambda row: int(row.id)):
        if t.relay_node_id is None:
            continue
        if tunnel_svc.transport_engine(t.transport) == "singbox":
            continue
        wg_port = (t.params or {}).get("wireguard_port")
        if not wg_port:
            continue
        relay_id = int(t.relay_node_id)
        delegate_port_by_relay.setdefault(relay_id, int(wg_port))
        if t.exit_node_id is None:
            panel_exit_relays.add(relay_id)
            pub = relay_pubkey_by_node.get(relay_id, "")
            if canonical_pubkey is None:
                canonical_pubkey = pub or None
                canonical_tunnel_id = int(t.id)
            elif pub and canonical_pubkey and pub != canonical_pubkey:
                if int(t.id) not in _pubkey_mismatch_logged:
                    _pubkey_mismatch_logged.add(int(t.id))
                    logger.warning(
                        "Tunnel %s relay WG pubkey differs from canonical panel-exit key; "
                        "subscriptions and host sync use the first tunnel's keys (tunnel %s)",
                        t.id,
                        canonical_tunnel_id,
                    )

    _relay_index_cache = TunnelRelayIndex(
        delegate_port_by_relay=delegate_port_by_relay,
        panel_exit_relays=frozenset(panel_exit_relays),
        canonical_pubkey=canonical_pubkey,
        relay_pubkey_by_node=relay_pubkey_by_node,
    )
    _relay_index_at = now
    return _relay_index_cache


def relay_wireguard_tunnel_port(db, node_id: int) -> Optional[int]:
    """Return the UDP capture port when ``node_id`` relays WG through Xray."""
    port = _tunnel_relay_index(db).delegate_port_by_relay.get(int(node_id))
    return int(port) if port is not None else None


def node_delegates_wireguard_to_tunnel(db, node_id: int) -> bool:
    """True when native WG on the relay must yield the listen port to Xray."""
    return relay_wireguard_tunnel_port(db, node_id) is not None


def prepare_relay_wireguard_tunnel(db, node_id: int, node_object) -> bool:
    """Stop native WG listeners on a relay before Xray captures ``wireguard_port``."""
    if not node_delegates_wireguard_to_tunnel(db, node_id):
        return False
    dbnode = crud.get_node_by_id(db, node_id)
    cfg = dbnode.wireguard if dbnode else None
    if cfg is None:
        return False
    from app.wireguard.sync import plain_wg_enabled
    from app.wireguard.transport import client_for_node

    client = client_for_node(node_object)
    if client is None:
        return False
    try:
        if plain_wg_enabled(cfg):
            client.down(cfg.interface)
        # AmneziaWG uses a separate UDP port from the tunnel's dokodemo
        # capture (plain listen_port) — leave AWG running on the relay.
        return True
    except Exception:
        return False


def ensure_tunnel_wireguard_port(db, tunnel) -> bool:
    """Seed ``params.wireguard_port`` from the relay node's plain WG listen port."""
    if tunnel.relay_node_id is None:
        return False
    if tunnel_svc.transport_engine(tunnel.transport) == "singbox":
        return False
    params = dict(tunnel.params or {})
    if params.get("wireguard_port"):
        return False

    from app.db.models import Node

    node = db.query(Node).filter(Node.id == tunnel.relay_node_id).first()
    cfg = node.wireguard if node else None
    if cfg is None or not plain_wg_enabled(cfg):
        return False

    params["wireguard_port"] = int(cfg.listen_port)
    tunnel.params = params
    return True


def panel_tunnel_exit_active(db) -> bool:
    """True when any enabled xray-engine tunnel terminates on the panel."""
    return bool(_tunnel_relay_index(db).panel_exit_relays)


def wireguard_target_port(db, tunnel) -> Optional[int]:
    """Exit-side native WireGuard listen port for dokodemo forwarding."""
    params = tunnel.params or {}
    explicit = params.get("wireguard_target_port")
    if explicit:
        return int(explicit)
    wg_port = params.get("wireguard_port")
    if not wg_port:
        return None
    if tunnel.exit_node_id is None:
        cfg = canonical_panel_exit_wireguard(db)
        if cfg is not None:
            return int(cfg.listen_port)
    return int(wg_port)


def canonical_panel_exit_wireguard(db):
    """Return the WG server row used by the panel-hosted tunnel exit."""
    from app.db.models import Node, Tunnel

    index = _tunnel_relay_index(db)
    if not index.panel_exit_relays or not index.canonical_pubkey:
        return None

    for t in sorted(
        db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all(),
        key=lambda row: int(row.id),
    ):
        if t.exit_node_id is not None or t.relay_node_id is None:
            continue
        if tunnel_svc.transport_engine(t.transport) == "singbox":
            continue
        if not (t.params or {}).get("wireguard_port"):
            continue
        node = db.query(Node).filter(Node.id == t.relay_node_id).first()
        cfg = node.wireguard if node else None
        if cfg is None or not plain_wg_enabled(cfg):
            continue
        if str(getattr(cfg, "public_key", "") or "") == (index.canonical_pubkey or ""):
            return cfg
    return None


def relay_tunnel_xray_ready(node_object) -> bool:
    """True when a relay node's Xray core is up and can capture WG UDP."""
    if not node_object:
        return False
    if getattr(node_object, "started", False):
        return True
    # ``connected`` only means the RPyC control channel is up — not that Xray
    # is listening. Always probe the remote core so health-check does not skip
    # reconnect while UDP is down, or reconnect while UDP is already up.
    try:
        return bool(node_object.get_version())
    except Exception:
        return False


def relay_wireguard_server_public_key(
    db,
    relay_node_id: int,
    *,
    node_object=None,
) -> Optional[str]:
    """Server pubkey clients must use when connecting through a relay."""
    index = _tunnel_relay_index(db)
    relay_id = int(relay_node_id)
    if relay_id not in index.delegate_port_by_relay:
        return None
    if relay_id in index.panel_exit_relays and index.canonical_pubkey:
        # Panel-exit tunnels always terminate on the canonical wg0 key; clients
        # must not use the relay's native WG pubkey (differs per node).
        return index.canonical_pubkey
    return index.relay_pubkey_by_node.get(relay_id)
