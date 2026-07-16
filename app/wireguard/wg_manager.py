"""WireGuard auto-scale orchestrator (panel-side).

When the ``wg_autoscale`` feature flag is enabled, plain WireGuard peers are
sharded across multiple kernel interfaces (200 peers each) with hot-add via
``wg set``. Existing clients on wg0 keep their IP/port/keys — the bootstrap
path imports them into ``wg_interfaces`` / ``wg_peers`` on first use.

AmneziaWG (typically wg1) continues on the legacy full-sync path.
"""
import ipaddress
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import Node, Proxy, User, WgInterface, WgPeer
from app.feature_flags import is_enabled
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.wireguard.keys import generate_keypair, generate_preshared_key
from app.wireguard.pool import WireGuardPeerIPAllocator
from app.wireguard.sync import plain_wg_enabled, server_interface_address

logger = logging.getLogger("nexus-wg-autoscale")

DEFAULT_MAX_PEERS = 200
BASE_SUBNET_PREFIX = "10.8"
BASE_LISTEN_PORT = 51820
SERVED_STATUSES = (UserStatus.active,)


class WireGuardAutoScaleError(Exception):
    pass


def autoscale_enabled() -> bool:
    return is_enabled("wg_autoscale")


def _reserved_interface_names(cfg) -> set:
    names: set = set()
    if cfg and getattr(cfg, "awg_enabled", False):
        names.add(getattr(cfg, "awg_interface", None) or "wg1")
    return names


def _max_peers_for_subnet(subnet: str) -> int:
    """Fill the configured subnet before opening another address space."""
    from app.wireguard.capacity import usable_peer_slots

    usable = usable_peer_slots(subnet)
    if usable <= 0:
        return DEFAULT_MAX_PEERS
    # Cap so a /16 does not create a single multi-million peer interface.
    return max(DEFAULT_MAX_PEERS, min(usable, 4094))


def _subnet_for_slot(slot: int, cfg=None) -> str:
    """Pick the peer subnet for an auto-scale interface slot.

    Slot 0 always follows the node's configured ``cfg.subnet`` (legacy / Finalmask
    pool) so we never invent a parallel ``10.8.0.0/24`` identity for the same
    users. Extra slots carve ``/24`` networks from a ``/16`` container around
    that subnet, skipping the primary range; only if that is exhausted do we
    fall back to the historic ``10.8.{slot}.0/24`` scheme.
    """
    if cfg is None or not getattr(cfg, "subnet", None):
        return f"{BASE_SUBNET_PREFIX}.{slot}.0/24"

    primary = ipaddress.ip_network(cfg.subnet, strict=False)
    if slot == 0:
        return str(primary)

    container = primary
    while container.prefixlen > 16:
        try:
            container = container.supernet(new_prefix=container.prefixlen - 1)
        except ValueError:
            break

    extras = [
        sub for sub in container.subnets(new_prefix=24)
        if not sub.overlaps(primary)
    ]
    idx = slot - 1
    if 0 <= idx < len(extras):
        return str(extras[idx])
    return f"{BASE_SUBNET_PREFIX}.{slot}.0/24"


def _port_for_slot(slot: int) -> int:
    return BASE_LISTEN_PORT + slot


def _next_slot(node_id: int, cfg, db: Session) -> Tuple[int, str]:
    reserved = _reserved_interface_names(cfg)
    existing = {row.name for row in db.query(WgInterface.name).filter(WgInterface.node_id == node_id).all()}
    slot = 0
    while True:
        name = f"wg{slot}"
        if name not in reserved and name not in existing:
            return slot, name
        slot += 1


def _normalize_allowed(address: str) -> str:
    raw = address.split("/")[0]
    ip = ipaddress.ip_address(raw)
    prefix = 32 if ip.version == 4 else 128
    return f"{ip}/{prefix}"


def _get_wg_proxy(db: Session, user_id: int) -> Optional[Proxy]:
    return (
        db.query(Proxy)
        .filter(Proxy.user_id == user_id, Proxy.type == ProxyTypes.WireGuard)
        .first()
    )


def _ensure_proxy_keys(db: Session, proxy: Proxy) -> dict:
    settings = dict(proxy.settings or {})
    if not settings.get("private_key") or not settings.get("public_key"):
        priv, pub = generate_keypair()
        settings.setdefault("private_key", priv)
        settings.setdefault("public_key", pub)
    if not settings.get("preshared_key"):
        settings["preshared_key"] = generate_preshared_key()
    proxy.settings = settings
    db.flush()
    return settings


def _pick_node(db: Session, node_id: Optional[int]) -> Optional[Node]:
    from app.db import crud

    if node_id is not None:
        return db.query(Node).filter(Node.id == node_id).first()
    nodes = crud.get_wireguard_nodes(db)
    return nodes[0] if nodes else None


def _node_client(dbnode: Node):
    from app.wireguard.operations import _node_object
    from app.wireguard.transport import client_for_node

    node_object = _node_object(dbnode.id)
    return client_for_node(node_object)


def _increment_peer_count(db: Session, iface: WgInterface, delta: int) -> None:
    iface.peer_count = max(0, int(iface.peer_count or 0) + delta)
    db.flush()


def bootstrap_legacy_interfaces(db: Session, dbnode: Node) -> None:
    """Import the existing plain WG interface + peers without changing clients."""
    cfg = dbnode.wireguard
    if cfg is None or not plain_wg_enabled(cfg):
        return
    existing = (
        db.query(WgInterface)
        .filter(WgInterface.node_id == dbnode.id, WgInterface.name == cfg.interface)
        .first()
    )
    if existing is not None:
        return

    slot = 0
    name = cfg.interface or "wg0"
    reserved = _reserved_interface_names(cfg)
    if name in reserved:
        slot, name = _next_slot(dbnode.id, cfg, db)

    iface = WgInterface(
        node_id=dbnode.id,
        name=name,
        subnet=cfg.subnet,
        listen_port=cfg.listen_port,
        private_key=cfg.private_key,
        public_key=cfg.public_key,
        peer_count=0,
        max_peers=_max_peers_for_subnet(cfg.subnet),
        slot_index=slot,
        created_at=datetime.utcnow(),
    )
    db.add(iface)
    db.flush()
    try:
        _create_interface_on_node(db, dbnode, iface)
    except Exception as exc:
        logger.warning(
            "bootstrap_legacy_interfaces: could not create %s on node %s: %s",
            iface.name,
            dbnode.id,
            exc,
        )

    from app.wireguard.operations import _all_wg_proxies

    imported = 0
    for proxy in _all_wg_proxies(db):
        if db.query(WgPeer).filter(WgPeer.user_id == proxy.user_id).first():
            continue
        settings = proxy.settings or {}
        address = settings.get("address")
        pubkey = settings.get("public_key")
        if not address or not pubkey:
            continue
        try:
            addr_ip = ipaddress.ip_address(str(address).split("/")[0])
            if addr_ip not in ipaddress.ip_network(cfg.subnet, strict=False):
                continue
        except ValueError:
            continue
        user = proxy.user
        active = bool(user and user.status in SERVED_STATUSES)
        peer = WgPeer(
            interface_id=iface.id,
            user_id=proxy.user_id,
            address=_normalize_allowed(address),
            private_key=settings["private_key"],
            public_key=pubkey,
            preshared_key=settings.get("preshared_key"),
            active=active,
            created_at=datetime.utcnow(),
        )
        db.add(peer)
        imported += 1
    _increment_peer_count(db, iface, imported)
    db.commit()
    logger.info(
        "Bootstrapped auto-scale interface %s on node %s with %d existing peers",
        iface.name,
        dbnode.id,
        imported,
    )


def _find_interface_with_capacity(db: Session, node_id: int) -> Optional[WgInterface]:
    return (
        db.query(WgInterface)
        .filter(
            WgInterface.node_id == node_id,
            WgInterface.peer_count < WgInterface.max_peers,
        )
        .order_by(WgInterface.slot_index)
        .with_for_update()
        .first()
    )


def _allocate_ip(db: Session, iface: WgInterface) -> str:
    used = [
        row.address
        for row in db.query(WgPeer.address).filter(WgPeer.interface_id == iface.id).all()
    ]
    allocator = WireGuardPeerIPAllocator(iface.subnet, used=used)
    address = allocator.allocate()
    if not address:
        raise WireGuardAutoScaleError(f"subnet {iface.subnet} exhausted on {iface.name}")
    return address


def _create_interface_on_node(db: Session, dbnode: Node, iface: WgInterface) -> None:
    client = _node_client(dbnode)
    if client is None or not hasattr(client, "autoscale_create_interface"):
        raise WireGuardAutoScaleError(f"node {dbnode.id} is not connected")
    cfg = dbnode.wireguard
    mtu = cfg.mtu if cfg else 1420
    client.autoscale_create_interface(
        {
            "name": iface.name,
            "listen_port": iface.listen_port,
            "private_key": iface.private_key,
            "public_key": iface.public_key,
            "subnet": iface.subnet,
            "mtu": mtu,
        }
    )


def create_interface(db: Session, dbnode: Node) -> WgInterface:
    """Provision a new WG interface on the node and persist metadata."""
    cfg = dbnode.wireguard
    if cfg is None:
        raise WireGuardAutoScaleError("node has no WireGuard config")

    slot, name = _next_slot(dbnode.id, cfg, db)
    priv, pub = generate_keypair()
    subnet = _subnet_for_slot(slot, cfg)
    iface = WgInterface(
        node_id=dbnode.id,
        name=name,
        subnet=subnet,
        listen_port=_port_for_slot(slot),
        private_key=priv,
        public_key=pub,
        peer_count=0,
        max_peers=_max_peers_for_subnet(subnet),
        slot_index=slot,
        created_at=datetime.utcnow(),
    )
    db.add(iface)
    db.flush()
    _create_interface_on_node(db, dbnode, iface)
    db.commit()
    db.refresh(iface)
    logger.info(
        "Created auto-scale interface %s on node %s (%s:%s)",
        iface.name,
        dbnode.id,
        iface.subnet,
        iface.listen_port,
    )
    return iface


def _find_or_create_interface(db: Session, dbnode: Node) -> WgInterface:
    iface = _find_interface_with_capacity(db, dbnode.id)
    if iface is not None:
        return iface
    return create_interface(db, dbnode)


def _endpoint(dbnode: Node, iface: WgInterface) -> str:
    cfg = dbnode.wireguard
    if cfg and cfg.endpoint and iface.name == (cfg.interface or "wg0"):
        return cfg.endpoint
    return f"{dbnode.address}:{iface.listen_port}"


def render_client_conf(dbnode: Node, iface: WgInterface, peer: WgPeer) -> str:
    from app.subscription.wireguard import render_wireguard_conf

    cfg = dbnode.wireguard
    mtu = cfg.mtu if cfg else 1420
    dns = cfg.dns if cfg else None
    return render_wireguard_conf(
        private_key=peer.private_key,
        address=peer.address,
        server_public_key=iface.public_key,
        endpoint=_endpoint(dbnode, iface),
        dns=dns,
        preshared_key=peer.preshared_key,
        mtu=mtu,
    )


def create_peer(
    db: Session,
    user_id: int,
    *,
    node_id: Optional[int] = None,
) -> dict:
    """Main entry point: assign or return a plain WG peer for ``user_id``.

    Returns ``{"conf": str, "interface": str, "address": str, "endpoint": str,
    "node_id": int}``. Idempotent — existing peers are returned unchanged.
    """
    if not autoscale_enabled():
        raise WireGuardAutoScaleError("wg_autoscale feature flag is disabled")

    dbnode = _pick_node(db, node_id)
    if dbnode is None or dbnode.wireguard is None:
        raise WireGuardAutoScaleError("no WireGuard node configured")

    bootstrap_legacy_interfaces(db, dbnode)

    proxy = _get_wg_proxy(db, user_id)
    if proxy is None:
        raise WireGuardAutoScaleError(f"user {user_id} has no WireGuard proxy")

    existing = db.query(WgPeer).filter(WgPeer.user_id == user_id).first()
    if existing is not None:
        iface = existing.interface
        dbnode = db.query(Node).filter(Node.id == iface.node_id).first() or dbnode
        return {
            "conf": render_client_conf(dbnode, iface, existing),
            "interface": iface.name,
            "address": existing.address,
            "endpoint": _endpoint(dbnode, iface),
            "node_id": iface.node_id,
            "public_key": existing.public_key,
        }

    settings = _ensure_proxy_keys(db, proxy)
    user = db.query(User).filter(User.id == user_id).first()
    active = bool(user and user.status in SERVED_STATUSES)

    iface = _find_or_create_interface(db, dbnode)
    address = _allocate_ip(db, iface)

    peer = WgPeer(
        interface_id=iface.id,
        user_id=user_id,
        address=address,
        private_key=settings["private_key"],
        public_key=settings["public_key"],
        preshared_key=settings.get("preshared_key"),
        active=active,
        created_at=datetime.utcnow(),
    )
    db.add(peer)
    _increment_peer_count(db, iface, 1)

    settings["address"] = address
    proxy.settings = settings
    db.flush()

    client = _node_client(dbnode)
    if client is None or not hasattr(client, "autoscale_hot_add_peer"):
        db.rollback()
        raise WireGuardAutoScaleError(f"node {dbnode.id} is not connected")

    allowed = _normalize_allowed(address) if active else "0.0.0.0/32"
    try:
        client.autoscale_hot_add_peer(
            iface.name,
            peer.public_key,
            allowed,
            preshared_key=peer.preshared_key,
        )
    except Exception as exc:
        db.rollback()
        raise WireGuardAutoScaleError(f"hot-add failed on {iface.name}: {exc}") from exc

    db.commit()
    db.refresh(peer)
    db.refresh(iface)

    return {
        "conf": render_client_conf(dbnode, iface, peer),
        "interface": iface.name,
        "address": peer.address,
        "endpoint": _endpoint(dbnode, iface),
        "node_id": dbnode.id,
        "public_key": peer.public_key,
    }


def toggle_peer(db: Session, user_id: int, *, active: bool) -> bool:
    """Soft-enable/disable a peer via allowed-ips (never removes peer config)."""
    peer = db.query(WgPeer).filter(WgPeer.user_id == user_id).first()
    if peer is None:
        return False

    iface = peer.interface
    dbnode = db.query(Node).filter(Node.id == iface.node_id).first()
    if dbnode is None:
        return False

    client = _node_client(dbnode)
    if client is None or not hasattr(client, "autoscale_toggle_peer"):
        return False

    peer.active = active
    db.commit()

    try:
        client.autoscale_toggle_peer(
            iface.name,
            peer.public_key,
            active=active,
            allowed_ips=_normalize_allowed(peer.address),
            preshared_key=peer.preshared_key,
        )
    except Exception as exc:
        logger.warning("toggle_peer for user %s failed: %s", user_id, exc)
        return False
    return True


def sync_user_statuses(db: Session) -> int:
    """Reconcile peer active flags with user status (returns count toggled)."""
    from app.wireguard.operations import _all_wg_proxies

    toggled = 0
    for proxy in _all_wg_proxies(db):
        peer = db.query(WgPeer).filter(WgPeer.user_id == proxy.user_id).first()
        if peer is None:
            continue
        user = proxy.user
        want_active = bool(user and user.status in SERVED_STATUSES)
        if peer.active != want_active:
            if toggle_peer(db, proxy.user_id, active=want_active):
                toggled += 1
    return toggled


def ensure_all_peers(db: Session) -> int:
    """Create missing auto-scale peers for every WG user (bootstrap helper)."""
    from app.wireguard.operations import _all_wg_proxies

    created = 0
    for proxy in _all_wg_proxies(db):
        if db.query(WgPeer).filter(WgPeer.user_id == proxy.user_id).first():
            continue
        try:
            create_peer(db, proxy.user_id)
            created += 1
        except WireGuardAutoScaleError as exc:
            logger.warning("ensure_all_peers skipped user %s: %s", proxy.user_id, exc)
    return created


def fetch_dump(db: Session, node_id: int) -> List[dict]:
    """Return ``wg show all dump`` rows enriched with user_id when known."""
    dbnode = db.query(Node).filter(Node.id == node_id).first()
    if dbnode is None:
        return []
    client = _node_client(dbnode)
    if client is None or not hasattr(client, "autoscale_show_dump"):
        return []

    pubkey_user: Dict[str, int] = {}
    for peer in db.query(WgPeer).join(WgInterface).filter(WgInterface.node_id == node_id).all():
        pubkey_user[peer.public_key] = peer.user_id

    rows = client.autoscale_show_dump() or []
    for row in rows:
        row["user_id"] = pubkey_user.get(row.get("public_key"))
    return rows


def collect_autoscale_transfer(db: Session, node_id: int) -> Dict[str, dict]:
    """Per-pubkey transfer counters across all auto-scale interfaces on a node."""
    dbnode = db.query(Node).filter(Node.id == node_id).first()
    if dbnode is None:
        return {}
    client = _node_client(dbnode)
    if client is None or not hasattr(client, "autoscale_transfer"):
        return {}

    ifaces = db.query(WgInterface.name).filter(WgInterface.node_id == node_id).all()
    merged: Dict[str, dict] = {}
    for (name,) in ifaces:
        part = client.autoscale_transfer(name) or {}
        for pubkey, counters in part.items():
            if pubkey not in merged:
                merged[pubkey] = {"rx": 0, "tx": 0}
            merged[pubkey]["rx"] += int(counters.get("rx", 0))
            merged[pubkey]["tx"] += int(counters.get("tx", 0))
    return merged
