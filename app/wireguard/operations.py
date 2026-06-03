"""WireGuard node sync orchestration (Phase 11.3).

Glues the pure planner (``app.wireguard.sync``) to the panel->node transport
(``app.wireguard.transport``): gather the users that hold a WireGuard proxy,
build each WG node's declarative spec and push it to the connected node.

Every entry point is best-effort and never raises into the caller — WireGuard
sync must never break the Xray user lifecycle. Peer collection and spec
building are kept injectable/pure so this is unit testable with fakes.
"""
import logging
from typing import List, Optional

from app.db import GetDB, crud
from app.db.models import Proxy
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.utils.concurrency import threaded_function
from app.wireguard.sync import WGUserPeer, build_node_spec
from app.wireguard.transport import client_for_node

logger = logging.getLogger("nexus-wg")

# Users in these statuses are actively served (carry a live peer). Anything
# else (disabled / limited / expired / on_hold) is pushed as inactive so the
# node drops the peer and traffic stops immediately.
SERVED_STATUSES = (UserStatus.active,)


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
        if not node.connected:
            return None
    except Exception:
        return None
    return node


def sync_node(db, dbnode, *, peers: Optional[List[WGUserPeer]] = None, node_object=None) -> bool:
    """Push the current peer set to one WG node. Returns True on a successful
    apply, False when the node is unconfigured/disconnected/unsupported."""
    cfg = dbnode.wireguard
    if cfg is None:
        return False

    node_object = node_object if node_object is not None else _node_object(dbnode.id)
    client = client_for_node(node_object)
    if client is None:
        return False

    if peers is None:
        peers = collect_wg_peers(db)

    spec = build_node_spec(
        interface=cfg.interface,
        listen_port=cfg.listen_port,
        private_key=cfg.private_key,
        subnet=cfg.subnet,
        peers=peers,
        mtu=cfg.mtu,
    )
    try:
        client.apply(spec)
        return True
    except Exception as exc:  # best-effort: log and move on
        logger.warning("WireGuard sync to node %s failed: %s", dbnode.id, exc)
        return False


def sync_all_nodes(db=None) -> int:
    """Re-sync every WireGuard node. Returns the count of successful applies."""
    def _run(session) -> int:
        wg_nodes = crud.get_wireguard_nodes(session)
        if not wg_nodes:
            return 0
        peers = collect_wg_peers(session)
        return sum(1 for n in wg_nodes if sync_node(session, n, peers=peers))

    if db is not None:
        return _run(db)
    with GetDB() as session:
        return _run(session)


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
