"""sing-box node sync orchestration (Hysteria2 / TUIC).

Glues the pure planner (``app.singbox.sync``) to the panel->node transport
(``app.singbox.transport``): gather the users that hold a Hysteria2/TUIC proxy,
build each sing-box node's declarative spec and push it to the connected node.

Every entry point is best-effort and never raises into the caller — sing-box
sync must never break the Xray user lifecycle.
"""
import logging
from typing import List, Optional

from app.db import GetDB, crud
from app.db.models import Proxy
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.singbox.sync import SBUser, build_node_spec
from app.singbox.transport import client_for_node
from app.utils.concurrency import threaded_function

logger = logging.getLogger("nexus-singbox")

SERVED_STATUSES = (UserStatus.active,)

_PROTOCOL_BY_TYPE = {
    ProxyTypes.Hysteria2: "hysteria2",
    ProxyTypes.TUIC: "tuic",
    ProxyTypes.AnyTLS: "anytls",
}


def collect_singbox_users(db) -> List[SBUser]:
    """Build the sing-box user list from every user that holds a Hysteria2 or
    TUIC proxy."""
    users: List[SBUser] = []
    proxies = (
        db.query(Proxy)
        .filter(Proxy.type.in_([ProxyTypes.Hysteria2, ProxyTypes.TUIC, ProxyTypes.AnyTLS]))
        .all()
    )
    for proxy in proxies:
        protocol = _PROTOCOL_BY_TYPE.get(ProxyTypes(proxy.type))
        if protocol is None:
            continue
        settings = proxy.settings or {}
        user = proxy.user
        users.append(
            SBUser(
                user_id=proxy.user_id,
                username=user.username if user else str(proxy.user_id),
                protocol=protocol,
                password=settings.get("password"),
                uuid=str(settings.get("uuid")) if settings.get("uuid") else None,
                active=bool(user and user.status in SERVED_STATUSES),
                speed_limit_up=getattr(user, "speed_limit_up", None) if user else None,
                speed_limit_down=getattr(user, "speed_limit_down", None) if user else None,
            )
        )
    return users


def _node_object(node_id: int, *, connect: bool = True):
    """Return the live node object. ``connect=False`` never dials (usage path)."""
    from app import xray

    node = xray.nodes.get(node_id)
    if node is None:
        return None
    conn = getattr(node, "connection", None)
    if conn is not None and not getattr(conn, "closed", True):
        return node
    if not connect:
        return None
    try:
        node.connect()
    except Exception:
        return None
    return node


def _cfg_to_dict(cfg) -> dict:
    return {
        "certificate_path": cfg.certificate_path,
        "key_path": cfg.key_path,
        "sni": cfg.sni,
        "clash_api_port": cfg.clash_api_port,
        "clash_api_secret": cfg.clash_api_secret,
        "hysteria2_enabled": cfg.hysteria2_enabled,
        "hysteria2_port": cfg.hysteria2_port,
        "hysteria2_up_mbps": cfg.hysteria2_up_mbps,
        "hysteria2_down_mbps": cfg.hysteria2_down_mbps,
        "hysteria2_obfs_password": cfg.hysteria2_obfs_password,
        "tuic_enabled": cfg.tuic_enabled,
        "tuic_port": cfg.tuic_port,
        "tuic_congestion_control": cfg.tuic_congestion_control,
        "anytls_enabled": cfg.anytls_enabled,
        "anytls_port": cfg.anytls_port,
    }


def sync_node(db, dbnode, *, users: Optional[List[SBUser]] = None, node_object=None) -> bool:
    """Push the current user set to one sing-box node. Returns True on a
    successful apply, False when unconfigured/disconnected/unsupported."""
    cfg = dbnode.singbox
    if cfg is None:
        return False

    node_object = node_object if node_object is not None else _node_object(dbnode.id)
    client = client_for_node(node_object)
    if client is None:
        return False

    if users is None:
        users = collect_singbox_users(db)

    spec = build_node_spec(_cfg_to_dict(cfg), users)
    try:
        from app.tunnel.singbox_inject import apply_singbox_endpoint_tunnels

        spec = apply_singbox_endpoint_tunnels(spec, dbnode.id)
    except Exception as exc:
        logger.warning(
            "sing-box tunnel inject for node %s failed: %s",
            dbnode.id,
            exc,
        )
    try:
        client.apply(spec)
        return True
    except Exception as exc:
        logger.warning("sing-box sync to node %s failed: %s", dbnode.id, exc)
        return False


def sync_all_nodes(db=None) -> int:
    """Re-sync every sing-box node. Returns the count of successful applies."""
    def _run(session) -> int:
        sb_nodes = crud.get_singbox_nodes(session)
        if not sb_nodes:
            return 0
        users = collect_singbox_users(session)
        return sum(1 for n in sb_nodes if sync_node(session, n, users=users))

    if db is not None:
        return _run(db)
    with GetDB() as session:
        return _run(session)


@threaded_function
def sync_user_change() -> None:
    """Lifecycle hook: re-sync sing-box nodes after any user add/update/remove.

    Cheap no-op when no sing-box node exists. Runs off-thread so it never blocks
    the Xray path.
    """
    try:
        sync_all_nodes()
    except Exception as exc:
        logger.warning("sing-box user-change sync failed: %s", exc)
