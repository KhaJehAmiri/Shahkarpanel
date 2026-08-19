"""sing-box node sync orchestration (Hysteria2 / TUIC).

Glues the pure planner (``app.singbox.sync``) to the panel->node transport
(``app.singbox.transport``): gather the users that hold a Hysteria2/TUIC proxy,
build each sing-box node's declarative spec and push it to the connected node.

Every entry point is best-effort and never raises into the caller — sing-box
sync must never break the Xray user lifecycle.
"""
import logging
import threading
from sqlalchemy.orm import joinedload
from typing import List, Optional, Tuple

from app.db import GetDB, crud
from app.db.models import Proxy
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.singbox.sync import SBUser, build_node_spec
from app.singbox.transport import client_for_node
from app.utils.concurrency import threaded_function

logger = logging.getLogger("shahkar-singbox")

SERVED_STATUSES = (UserStatus.active,)

_PROTOCOL_BY_TYPE = {
    ProxyTypes.Hysteria2: "hysteria2",
    ProxyTypes.TUIC: "tuic",
    ProxyTypes.AnyTLS: "anytls",
}

_sb_sync_lock = threading.Lock()
_sb_sync_in_flight = False
_sb_sync_queued = False
_sb_sync_timer: Optional[threading.Timer] = None
_SB_SYNC_DEBOUNCE_SEC = 2.0


def _node_channel_live(node_object) -> bool:
    """True when the control channel is already open — never dials."""
    if node_object is None:
        return False
    checker = getattr(node_object, "has_live_rpyc", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    conn = getattr(node_object, "connection", None)
    return conn is not None and not getattr(conn, "closed", True)


def collect_singbox_users(db) -> List[SBUser]:
    """Build the sing-box user list from every user that holds a Hysteria2 or
    TUIC proxy."""
    users: List[SBUser] = []
    proxies = (
        db.query(Proxy).options(joinedload(Proxy.user))
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
                active=_singbox_user_active(user),
                speed_limit_up=getattr(user, "speed_limit_up", None) if user else None,
                speed_limit_down=getattr(user, "speed_limit_down", None) if user else None,
            )
        )
    return users


def _singbox_user_active(user) -> bool:
    if not user or user.status not in SERVED_STATUSES:
        return False
    try:
        from app.utils.device_exclusivity import PROTO_SINGBOX, is_protocol_held

        if is_protocol_held(user, PROTO_SINGBOX):
            return False
    except Exception:
        pass
    return True


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

    node_object = node_object if node_object is not None else _node_object(dbnode.id, connect=False)
    if not _node_channel_live(node_object):
        # Health check reconnects; dialling here piles threads behind a dead
        # peer and holds the caller's DB session open the whole time.
        return False
    client = client_for_node(node_object)
    if client is None:
        return False

    if users is None:
        users = collect_singbox_users(db)

    spec = build_node_spec(_cfg_to_dict(cfg), users)
    try:
        from app.tunnel.singbox_inject import (
            apply_singbox_endpoint_tunnels,
            apply_singbox_warp_bridge,
        )

        spec = apply_singbox_endpoint_tunnels(spec, dbnode.id)
        spec = apply_singbox_warp_bridge(spec, dbnode.id)
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


def _sync_node_snapshot(node_id: int, cfg: dict, users: List[SBUser]) -> bool:
    """Apply a previously snapshotted config — no DB session held."""
    node_object = _node_object(node_id, connect=False)
    if not _node_channel_live(node_object):
        return False
    client = client_for_node(node_object)
    if client is None:
        return False
    spec = build_node_spec(cfg, users)
    try:
        from app.tunnel.singbox_inject import (
            apply_singbox_endpoint_tunnels,
            apply_singbox_warp_bridge,
        )

        spec = apply_singbox_endpoint_tunnels(spec, node_id)
        spec = apply_singbox_warp_bridge(spec, node_id)
    except Exception as exc:
        logger.warning("sing-box tunnel inject for node %s failed: %s", node_id, exc)
    try:
        client.apply(spec)
        return True
    except Exception as exc:
        logger.warning("sing-box sync to node %s failed: %s", node_id, exc)
        return False


def sync_all_nodes(db=None) -> int:
    """Re-sync every sing-box node. Returns the count of successful applies.

    DB work finishes before any RPyC call so a hung node cannot leave the
    session ``idle in transaction`` and starve subscriptions of pool slots.
    """
    def _snapshot(session) -> Tuple[List[Tuple[int, dict]], List[SBUser]]:
        sb_nodes = crud.get_singbox_nodes(session)
        if not sb_nodes:
            return [], []
        users = collect_singbox_users(session)
        snaps = [
            (int(n.id), _cfg_to_dict(n.singbox))
            for n in sb_nodes
            if n.singbox is not None
        ]
        return snaps, users

    if db is not None:
        snaps, users = _snapshot(db)
    else:
        with GetDB() as session:
            snaps, users = _snapshot(session)

    return sum(1 for nid, cfg in snaps if _sync_node_snapshot(nid, cfg, users))


def _run_coalesced_sb_sync() -> None:
    global _sb_sync_in_flight, _sb_sync_queued, _sb_sync_timer
    with _sb_sync_lock:
        _sb_sync_timer = None
        if _sb_sync_in_flight:
            _sb_sync_queued = True
            return
        _sb_sync_in_flight = True
        _sb_sync_queued = False
    try:
        sync_all_nodes()
    except Exception as exc:
        logger.warning("sing-box user-change sync failed: %s", exc)
    finally:
        rerun = False
        with _sb_sync_lock:
            _sb_sync_in_flight = False
            if _sb_sync_queued:
                _sb_sync_queued = False
                rerun = True
        if rerun:
            sync_user_change()


def sync_user_change() -> None:
    from app.runtime_role import delegate_to_worker

    if delegate_to_worker("user_change"):
        return
    """Lifecycle hook: re-sync sing-box nodes after any user add/update/remove.

    Debounced + single-flight. Without this, every user mutation spawned a new
    daemon thread that opened a DB session and then blocked on RPyC — hundreds
    of threads and ``idle in transaction`` connections starved the API.
    """
    global _sb_sync_timer
    with _sb_sync_lock:
        if _sb_sync_timer is not None:
            _sb_sync_timer.cancel()
            _sb_sync_timer = None
        if _sb_sync_in_flight:
            _sb_sync_queued = True
            return
        timer = threading.Timer(_SB_SYNC_DEBOUNCE_SEC, _run_coalesced_sb_sync)
        timer.daemon = True
        _sb_sync_timer = timer
        timer.start()
