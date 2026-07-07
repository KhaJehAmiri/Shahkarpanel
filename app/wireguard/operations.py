"""WireGuard node sync orchestration (Phase 11.3).

Glues the pure planner (``app.wireguard.sync``) to the panel->node transport
(``app.wireguard.transport``): gather the users that hold a WireGuard proxy,
build each WG node's declarative spec and push it to the connected node.

Every entry point is best-effort and never raises into the caller — WireGuard
sync must never break the Xray user lifecycle. Peer collection and spec
building are kept injectable/pure so this is unit testable with fakes.
"""
import logging
import threading
from typing import Dict, List, Optional

from app.db import GetDB, crud
from app.db.models import Proxy
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.utils.concurrency import threaded_function
from app.wireguard.pool import WireGuardPeerIPAllocator
from app.wireguard.sync import (WGUserPeer, amneziawg_enabled,
                                build_node_specs, plain_wg_enabled)
from app.wireguard.transport import WireGuardTransportError, client_for_node

logger = logging.getLogger("nexus-wg")

# Users in these statuses are actively served (carry a live peer). Anything
# else (disabled / limited / expired / on_hold) is pushed as inactive so the
# node drops the peer and traffic stops immediately.
SERVED_STATUSES = (UserStatus.active,)


def _all_wg_proxies(db) -> List[Proxy]:
    return db.query(Proxy).filter(Proxy.type == ProxyTypes.WireGuard).all()


def _settings_key_for_subnet(cfg, subnet: str) -> str:
    if cfg and getattr(cfg, "awg_subnet", None) == subnet:
        return "awg_address"
    return "address"


# Serialize "read used addresses -> pick free one -> commit" per subnet.
# Without this, two concurrent requests (e.g. two devices of the same tenant
# fetching their subscription for the first time) can both read the same
# "used" set before either commits, and both hand out the *same* free IP to
# two different users (AUDIT_FINDINGS.md M1). The panel always runs as a
# single process (see main.py: "Do NOT change workers count"), so a
# per-subnet in-process lock fully closes the race for every deployment that
# actually exists today; this mirrors the atomic-claim pattern already used
# for node connect/restart (H6/H7).
_subnet_locks_guard = threading.Lock()
_subnet_locks: Dict[str, threading.Lock] = {}


def _lock_for_subnet(subnet: str) -> threading.Lock:
    with _subnet_locks_guard:
        lock = _subnet_locks.get(subnet)
        if lock is None:
            lock = threading.Lock()
            _subnet_locks[subnet] = lock
        return lock


def ensure_user_address(db, proxy: Proxy, subnet: str, *, cfg=None) -> Optional[str]:
    """Allocate a peer IP from ``subnet`` for plain or AWG stack."""
    from app.wireguard.kind import wg_wants_awg_address, wg_wants_plain_address

    key = _settings_key_for_subnet(cfg, subnet)
    settings = dict(proxy.settings or {})
    wants = wg_wants_awg_address if key == "awg_address" else wg_wants_plain_address
    if not wants(settings):
        return settings.get(key)
    if settings.get(key):
        return settings[key]

    with _lock_for_subnet(subnet):
        # Re-check under the lock: another thread may have allocated (and
        # committed) an address for this exact proxy while we were waiting,
        # or the caller's copy of `proxy` may simply be stale.
        if proxy.id is not None:
            db.refresh(proxy)
        settings = dict(proxy.settings or {})
        if settings.get(key):
            return settings[key]

        used = [
            p.settings.get(key)
            for p in _all_wg_proxies(db)
            if p.settings and p.settings.get(key)
        ]
        allocator = WireGuardPeerIPAllocator(subnet, used=used)
        address = allocator.allocate()
        if not address:
            logger.warning("WireGuard subnet %s exhausted; cannot allocate peer IP", subnet)
            return None

        settings[key] = address
        proxy.settings = settings
        db.commit()
        return address


def ensure_addresses_for_subnet(db, subnet: str, *, cfg=None) -> None:
    """Allocate peer IPs for WG users missing one in ``subnet``."""
    from app.wireguard.kind import wg_wants_awg_address, wg_wants_plain_address

    key = _settings_key_for_subnet(cfg, subnet)
    wants = wg_wants_awg_address if key == "awg_address" else wg_wants_plain_address
    # Shares the per-subnet lock with `ensure_user_address` so this batch pass
    # can never race with (or double-allocate on top of) a concurrent
    # per-request allocation for the same subnet.
    with _lock_for_subnet(subnet):
        proxies = _all_wg_proxies(db)
        used = [p.settings.get(key) for p in proxies if p.settings and p.settings.get(key)]
        allocator = WireGuardPeerIPAllocator(subnet, used=used)
        for proxy in proxies:
            settings = dict(proxy.settings or {})
            if not wants(settings):
                continue
            if settings.get(key):
                continue
            address = allocator.allocate()
            if not address:
                logger.warning("WireGuard subnet %s exhausted while assigning peers", subnet)
                break
            settings[key] = address
            proxy.settings = settings
        db.commit()


def ensure_preshared_key(db, proxy: Proxy) -> dict:
    """Ensure a WireGuard proxy has a preshared key (required by AmneziaVPN on iOS)."""
    from app.wireguard.keys import generate_preshared_key

    settings = dict(proxy.settings or {})
    if not settings.get("preshared_key"):
        settings["preshared_key"] = generate_preshared_key()
        proxy.settings = settings
        db.commit()
    return settings


def collect_wg_peers(db) -> List[WGUserPeer]:
    """Build the WireGuard peer list from every user that holds a WG proxy."""
    peers: List[WGUserPeer] = []
    proxies = db.query(Proxy).filter(Proxy.type == ProxyTypes.WireGuard).all()
    for proxy in proxies:
        settings = proxy.settings or {}
        public_key = settings.get("public_key")
        if not public_key:
            continue
        user = proxy.user
        peers.append(
            WGUserPeer(
                user_id=proxy.user_id,
                public_key=public_key,
                address=settings.get("address") or "",
                preshared_key=settings.get("preshared_key") or None,
                active=bool(user and user.status in SERVED_STATUSES),
                awg_address=settings.get("awg_address") or "",
                speed_limit_up=getattr(user, "speed_limit_up", None) if user else None,
                speed_limit_down=getattr(user, "speed_limit_down", None) if user else None,
            )
        )
    return peers


def _node_object(node_id: int):
    """Return the live connection object for a node, if connected."""
    from app import xray

    node = xray.nodes.get(node_id)
    if node is None:
        return None
    try:
        conn = getattr(node, "connection", None)
        if conn is None or conn.closed:
            node.connect()
        else:
            conn.ping()
    except Exception:
        try:
            node.connect()
        except Exception:
            return None
    return node


def sync_node(db, dbnode, *, peers: Optional[List[WGUserPeer]] = None, node_object=None) -> bool:
    """Push the current peer set to one WG node. Returns True on a successful
    apply, False when the node is unconfigured/disconnected/unsupported."""
    from app.wireguard.wg_manager import autoscale_enabled

    cfg = dbnode.wireguard
    if cfg is None:
        return False

    node_object = node_object if node_object is not None else _node_object(dbnode.id)
    client = client_for_node(node_object)
    if client is None:
        return False

    if autoscale_enabled() and plain_wg_enabled(cfg):
        from app.wireguard.wg_manager import bootstrap_legacy_interfaces, sync_user_statuses

        bootstrap_legacy_interfaces(db, dbnode)
        sync_user_statuses(db)

    if peers is None:
        if plain_wg_enabled(cfg) and not autoscale_enabled():
            ensure_addresses_for_subnet(db, cfg.subnet, cfg=cfg)
        if amneziawg_enabled(cfg):
            ensure_addresses_for_subnet(db, cfg.awg_subnet, cfg=cfg)
            crud.ensure_awg_server_keys(db, dbnode)
            db.refresh(cfg)
        peers = collect_wg_peers(db)

    try:
        if autoscale_enabled() and plain_wg_enabled(cfg) and amneziawg_enabled(cfg):
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
            from app.wireguard.sync import build_node_spec, awg_params_from_cfg
            from app.wireguard.awg import AWG_RECOMMENDED_MTU

            crud.ensure_awg_server_keys(db, dbnode)
            db.refresh(cfg)
            awg_spec = build_node_spec(
                interface=cfg.awg_interface,
                listen_port=cfg.awg_listen_port,
                private_key=cfg.awg_private_key,
                subnet=cfg.awg_subnet,
                peers=awg_peers,
                mtu=AWG_RECOMMENDED_MTU,
                amnezia=awg_params_from_cfg(cfg) or None,
            )
            specs = [awg_spec]
        elif autoscale_enabled() and plain_wg_enabled(cfg):
            return True
        else:
            specs = build_node_specs(cfg, peers)
        if not specs:
            return False
        client.apply_specs(specs)
        return True
    except Exception as exc:  # best-effort: log and move on
        logger.warning("WireGuard sync to node %s failed: %s", dbnode.id, exc)
        return False


def sync_all_nodes(db=None) -> int:
    """Re-sync every WireGuard node. Returns the count of successful applies."""
    from app.wireguard.wg_manager import autoscale_enabled, ensure_all_peers

    def _run(session) -> int:
        wg_nodes = crud.get_wireguard_nodes(session)
        if not wg_nodes:
            return 0
        if autoscale_enabled():
            ensure_all_peers(session)
        # Single-subnet model: allocate any missing peer IPs from the first
        # configured node's subnet before computing the shared peer set.
        for n in wg_nodes:
            cfg = n.wireguard
            if cfg is None:
                continue
            if plain_wg_enabled(cfg) and not autoscale_enabled():
                ensure_addresses_for_subnet(session, cfg.subnet, cfg=cfg)
            if amneziawg_enabled(cfg):
                ensure_addresses_for_subnet(session, cfg.awg_subnet, cfg=cfg)
                crud.ensure_awg_server_keys(session, n)
            break
        peers = collect_wg_peers(session)
        return sum(1 for n in wg_nodes if sync_node(session, n, peers=peers))

    if db is not None:
        return _run(db)
    with GetDB() as session:
        return _run(session)


def prepare_awg_peer_for_connect(dbnode, public_key: str) -> bool:
    """Clear a learned AWG endpoint so the client can reconnect with a new UDP port.

    Returns ``True`` once the clear request was actually delivered to the
    node (regardless of whether an endpoint needed clearing — e.g. a first
    connect is a legitimate no-op). Raises ``ValueError`` for a request that
    can never succeed as configured (no pubkey / no WG config / AWG
    disabled) and ``WireGuardTransportError`` when the node itself could not
    be reached or does not support the operation.

    Previously this silently returned ``None`` on *every* failure path, so
    the ``/wireguard/prepare`` route always answered ``{"ok": true}`` even
    when nothing happened on the node — the client believed the stale
    endpoint was cleared and reconnect kept failing (AUDIT_FINDINGS.md H2).
    """
    if not public_key:
        raise ValueError("No public key to prepare")
    cfg = dbnode.wireguard
    if cfg is None:
        raise ValueError("Node has no WireGuard configuration")
    if not amneziawg_enabled(cfg):
        raise ValueError("AmneziaWG is not enabled on this node")
    iface = cfg.awg_interface or "wg1"
    node_object = _node_object(dbnode.id)
    client = client_for_node(node_object)
    if client is None:
        raise WireGuardTransportError(f"Node {dbnode.id} is not connected")
    if not hasattr(client, "prepare_peer_for_connect"):
        raise WireGuardTransportError("Node does not support AWG endpoint prepare")
    try:
        client.prepare_peer_for_connect(iface, public_key)
    except Exception as exc:
        logger.warning("AWG peer prepare for %s failed: %s", public_key[:8], exc)
        raise WireGuardTransportError(f"Failed to prepare peer: {exc}") from exc
    return True


@threaded_function
def sync_user_change() -> None:
    """Lifecycle hook: re-sync WG nodes after any user add/update/remove.

    Pushes the full (idempotent) peer set via ``wg syncconf`` so additions,
    removals and status changes all converge. Cheap no-op when no WG node
    exists. Runs off-thread so it never blocks the Xray path.
    """
    try:
        sync_all_nodes()
    except Exception as exc:
        logger.warning("WireGuard user-change sync failed: %s", exc)
