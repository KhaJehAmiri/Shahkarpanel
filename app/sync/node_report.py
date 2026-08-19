"""Per-node desired vs reported (phase 4).

Worker writes last_ack / fingerprints / tunnel flags. API never reads
``xray.nodes`` for the node list — that map is empty in the HTTP process.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("uvicorn.error")

# Health ticks skip under Finalmask/RPyC load; 90s made connected nodes
# flicker Connecting on the dashboard even though the session was live.
STALE_ACK_SEC = 180
_last_health: dict[int, str] = {}


def desired_fingerprint(db: Session, dbnode) -> str:
    """Stable hash of the policy the panel wants on this node."""
    from app.services.xray_node import node_xray_inbound_tags
    from app.wireguard.xray_native import xray_native_wg_enabled

    tags = node_xray_inbound_tags(db, int(dbnode.id))
    tag_list = sorted(tags) if tags is not None else ["*"]
    cfg = getattr(dbnode, "wireguard", None)
    payload = {
        "warp_enabled": bool(getattr(dbnode, "warp_enabled", False)),
        "warp_mode": str(getattr(dbnode, "warp_mode", "") or ""),
        "warp_tag": str(getattr(dbnode, "warp_tag", "") or ""),
        "tags": tag_list,
        "xray_wg": bool(cfg is not None and xray_native_wg_enabled(cfg)),
        "xray_wg_port": int(getattr(cfg, "xray_wg_listen_port", 0) or 0) if cfg else 0,
        "core_kind": str(getattr(dbnode, "core_kind", "") or ""),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _peer_count(db: Session, node_id: int) -> int:
    from sqlalchemy import func

    from app.db.models import WgInterface, WgPeer

    n = (
        db.query(func.count(WgPeer.id))
        .join(WgInterface, WgPeer.interface_id == WgInterface.id)
        .filter(WgInterface.node_id == int(node_id), WgPeer.active.is_(True))
        .scalar()
    )
    return int(n or 0)


def refresh_desired(db: Session, dbnode, *, commit: bool = True) -> None:
    """Recompute desired hash; mark drift if live apply is behind policy."""
    desired = desired_fingerprint(db, dbnode)
    dbnode.desired_fingerprint = desired
    reported = getattr(dbnode, "reported_fingerprint", None)
    if reported and reported != desired:
        dbnode.drift = True
        dbnode.drift_reason = "policy changed since last live apply"
    elif reported == desired:
        dbnode.drift = False
        dbnode.drift_reason = None
    if commit:
        db.commit()


def stamp_applied(
    db: Session,
    dbnode,
    *,
    commit: bool = True,
    control_tunneled: Optional[bool] = None,
) -> None:
    """Call after a successful connect / config apply (live ACK of this policy)."""
    desired = desired_fingerprint(db, dbnode)
    now = datetime.utcnow()
    dbnode.desired_fingerprint = desired
    dbnode.reported_fingerprint = desired
    dbnode.drift = False
    dbnode.drift_reason = None
    dbnode.last_ack_at = now
    dbnode.last_stats_ok = now
    if control_tunneled is not None:
        dbnode.control_tunnel_ok = bool(control_tunneled)
    if commit:
        db.commit()


def record_probe(
    node_id: int,
    *,
    latency_ms: Optional[float] = None,
    stats_ok: bool = True,
    control_tunneled: Optional[bool] = None,
    ssh_ok: Optional[bool] = None,
    peer_count: Optional[int] = None,
) -> None:
    """Persist a successful (or partial) health probe. Worker-only."""
    from app.db import GetDB, crud
    from app.control_tunnel import has_ssh_for_host

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, int(node_id))
        if dbnode is None:
            return
        now = datetime.utcnow()
        if latency_ms is not None:
            dbnode.latency_ms = float(latency_ms)
        dbnode.last_health = now
        if stats_ok:
            dbnode.last_ack_at = now
            dbnode.last_stats_ok = now
        if control_tunneled is not None:
            dbnode.control_tunnel_ok = bool(control_tunneled)
        if ssh_ok is None:
            host = (dbnode.provision_host or dbnode.address or "").strip()
            try:
                ssh_ok = bool(host and has_ssh_for_host(host))
            except Exception:
                ssh_ok = None
        if ssh_ok is not None:
            dbnode.ssh_ok = bool(ssh_ok)
        if peer_count is not None:
            dbnode.reported_peer_count = int(peer_count)
        else:
            cursor = getattr(dbnode, "sync_cursor", None)
            if cursor is not None and int(getattr(cursor, "peers_done", 0) or 0):
                dbnode.reported_peer_count = int(cursor.peers_done or 0)
            else:
                dbnode.reported_peer_count = _peer_count(db, int(node_id))
        refresh_desired(db, dbnode, commit=False)
        db.commit()
        hs = health_status(dbnode, cursor_status=cursor_busy_status(getattr(dbnode, "sync_cursor", None)))
        prev = _last_health.get(int(node_id))
        _last_health[int(node_id)] = hs
        if prev is not None and prev != hs:
            try:
                from app.sync.live import publish_event

                st = getattr(dbnode.status, "value", dbnode.status)
                publish_event(
                    "node.status",
                    {
                        "node_id": int(node_id),
                        "name": dbnode.name,
                        "status": str(st or ""),
                        "health_status": hs,
                    },
                )
            except Exception:
                pass


def health_status(dbnode, *, cursor_status: Optional[str] = None) -> str:
    """UI status: never trust in-process RPyC from the API worker."""
    from app.models.node import NodeStatus

    st = getattr(dbnode, "status", None)
    val = getattr(st, "value", st)
    if val == NodeStatus.disabled.value:
        return "disabled"
    if val == NodeStatus.error.value:
        return "error"
    if val == NodeStatus.connecting.value:
        return "connecting"
    if cursor_status and cursor_status not in ("converged", "", None):
        return "syncing"
    if getattr(dbnode, "drift", False):
        return "drifted"
    stamps = [
        t
        for t in (
            getattr(dbnode, "last_ack_at", None),
            getattr(dbnode, "last_health", None),
        )
        if t is not None
    ]
    if not stamps:
        return "connecting"
    try:
        age = (datetime.utcnow() - max(stamps)).total_seconds()
    except Exception:
        age = 0
    if age > STALE_ACK_SEC:
        return "connecting"
    return "connected"


def cursor_busy_status(cursor) -> Optional[str]:
    if cursor is None:
        return None
    st = getattr(cursor, "status", None) or ""
    if st and st not in ("converged",):
        return st
    try:
        done = int(getattr(cursor, "peers_done", 0) or 0)
        total = int(getattr(cursor, "peers_total", 0) or 0)
    except (TypeError, ValueError):
        return None
    if total and done < total:
        return "syncing"
    return None


def decorate_node_response(row, dbnode, *, cursor=None) -> None:
    """Fill API-only fields. Never read ``xray.nodes`` here."""
    row.health_status = health_status(
        dbnode, cursor_status=cursor_busy_status(cursor)
    )
    row.control_tunneled = bool(getattr(dbnode, "control_tunnel_ok", False))


def converge_node(node_id: int) -> None:
    """Reconnect and resume WG cursor so desired/reported can meet."""
    from app.xray.operations import connect_node

    connect_node(int(node_id))
    try:
        from app.wireguard.sync_engine import on_node_connected

        on_node_connected(int(node_id))
    except Exception:
        logger.exception("converge WG cursor for node %s failed", node_id)
