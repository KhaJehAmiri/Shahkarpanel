"""Live dashboard snapshot on Redis (phase 6).

Worker writes a compact KPI tick every second and publishes it on a pub/sub
channel. API WebSocket clients subscribe; HTTP handlers read the same key.
Nothing here QueryStats the fleet or walks ``xray.nodes``.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("uvicorn.error")

SNAPSHOT_KEY = "shahkar:live:snapshot"
LIVE_CHANNEL = "shahkar:live"
HOST_KEY = "shahkar:live:host"
SNAPSHOT_TTL = 15
FRESH_SEC = 8.0
_HOST_FIELDS = ("cpu_usage", "cpu_cores", "mem_used", "mem_total")
# User/node census is heavier than host gauges; reuse across 1s ticks.
_CENSUS_TTL_SEC = 2.0
_census_lock = threading.Lock()
_census_cache: Optional[dict] = None
_census_mono: float = 0.0


_redis_lock = threading.Lock()
_redis_client = None


def _redis():
    """Persistent Redis client — a new TCP handshake every tick stalled Overview."""
    global _redis_client
    from config import REDIS_URL

    if not REDIS_URL:
        return None
    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        try:
            import redis

            _redis_client = redis.Redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=0.4,
                socket_timeout=0.4,
                health_check_interval=10,
            )
            return _redis_client
        except Exception:
            _redis_client = None
            return None


def _drop_redis() -> None:
    global _redis_client
    with _redis_lock:
        client = _redis_client
        _redis_client = None
    if client is None:
        return
    try:
        client.close()
    except Exception:
        pass


def _host_overlay(client) -> dict:
    """Fresh CPU/RAM from the isolated host-tick process."""
    try:
        raw = client.get(HOST_KEY)
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return {k: data[k] for k in _HOST_FIELDS if k in data}
    except Exception:
        return {}


def publish_raw(payload: dict) -> None:
    """SET snapshot (ticks only) + PUBLISH every live message."""
    client = _redis()
    if client is None:
        return
    try:
        if payload.get("kind") == "tick":
            host = _host_overlay(client)
            if host:
                payload = dict(payload)
                for key, val in host.items():
                    if key == "cpu_usage" and not val and payload.get("cpu_usage"):
                        continue
                    payload[key] = val
        raw = json.dumps(payload, default=str, separators=(",", ":"))
        pipe = client.pipeline()
        if payload.get("kind") == "tick":
            pipe.set(SNAPSHOT_KEY, raw, ex=SNAPSHOT_TTL)
        pipe.publish(LIVE_CHANNEL, raw)
        pipe.execute()
    except Exception:
        logger.debug("live publish failed", exc_info=True)
        _drop_redis()


def load_snapshot() -> Optional[dict]:
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(SNAPSHOT_KEY)
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        data.update(_host_overlay(client))
        return data
    except Exception:
        _drop_redis()
        return None


def snapshot_age(snap: Optional[dict]) -> Optional[float]:
    if not snap:
        return None
    try:
        return max(0.0, time.time() - float(snap.get("t") or 0))
    except (TypeError, ValueError):
        return None


def snapshot_fresh(snap: Optional[dict], *, max_age: float = FRESH_SEC) -> bool:
    age = snapshot_age(snap)
    return age is not None and age <= max_age


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return default


def _speed(v: Any) -> int:
    n = _int(v)
    return n if n >= 0 else 0


def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v if v is not None else default)
    except (TypeError, ValueError):
        return default


def _core_uptime() -> tuple[int, int, bool, str]:
    """Worker-local Xray only. Never import ``app.xray`` (that load blocks ticks)."""
    try:
        from app.sync.core_status import snapshot

        return snapshot()
    except Exception:
        return 0, 0, False, ""


def _empty_census() -> dict:
    return {
        "online_users": 0,
        "nodes_connected": 0,
        "counts": {"total": 0, "by_status": {}},
        "uplink": 0,
        "downlink": 0,
        "by_admin": {},
        "nodes_by_tenant": {},
    }


def _query_census() -> dict:
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.db import GetDB, crud
    from app.db.models import Node, User
    from app.models.node import NodeStatus
    from app.models.user import UserStatus
    from config import ONLINE_WINDOW_MINUTES

    out = _empty_census()
    with GetDB() as db:
        try:
            system = crud.get_system_usage(db)
            if system is not None:
                out["uplink"] = int(getattr(system, "uplink", 0) or 0)
                out["downlink"] = int(getattr(system, "downlink", 0) or 0)
        except Exception:
            logger.debug("live snapshot system usage failed", exc_info=True)
        try:
            out["counts"] = crud.get_user_status_counts(db)
        except Exception:
            logger.debug("live snapshot status counts failed", exc_info=True)
        try:
            out["online_users"] = int(crud.count_online_users(db) or 0)
        except Exception:
            logger.debug("live snapshot online count failed", exc_info=True)
        try:
            out["nodes_connected"] = int(
                db.query(func.count(Node.id))
                .filter(Node.status == NodeStatus.connected)
                .scalar()
                or 0
            )
        except Exception:
            logger.debug("live snapshot node count failed", exc_info=True)

        cutoff = datetime.utcnow() - timedelta(minutes=ONLINE_WINDOW_MINUTES)
        by_admin: dict[str, dict[str, int]] = {}
        try:
            for admin_id, n in (
                db.query(User.admin_id, func.count(User.id))
                .filter(
                    User.online_at.isnot(None),
                    User.online_at >= cutoff,
                    User.status.in_((UserStatus.active, UserStatus.on_hold)),
                )
                .group_by(User.admin_id)
                .all()
            ):
                key = str(int(admin_id or 0))
                by_admin.setdefault(key, {})["online"] = int(n or 0)
        except Exception:
            logger.debug("live snapshot by_admin online failed", exc_info=True)
        try:
            for admin_id, status, n in (
                db.query(User.admin_id, User.status, func.count(User.id))
                .group_by(User.admin_id, User.status)
                .all()
            ):
                key = str(int(admin_id or 0))
                row = by_admin.setdefault(key, {})
                st = status.value if hasattr(status, "value") else str(status or "")
                count = int(n or 0)
                row["total"] = int(row.get("total") or 0) + count
                if st:
                    row[f"users_{st}"] = count
        except Exception:
            logger.debug("live snapshot by_admin status failed", exc_info=True)
        out["by_admin"] = by_admin
        nodes_by_tenant: dict[str, int] = {}
        try:
            for tenant_id, n in (
                db.query(Node.tenant_id, func.count(Node.id))
                .filter(Node.status == NodeStatus.connected)
                .group_by(Node.tenant_id)
                .all()
            ):
                nodes_by_tenant[str(int(tenant_id or 0))] = int(n or 0)
        except Exception:
            logger.debug("live snapshot nodes_by_tenant failed", exc_info=True)
        out["nodes_by_tenant"] = nodes_by_tenant
    return out


def load_census(*, force: bool = False) -> dict:
    """Cached user/node totals. The 1s WebSocket tick must never wait on SQL."""
    global _census_cache, _census_mono
    if not force:
        with _census_lock:
            return _census_cache if _census_cache is not None else _empty_census()
    now = time.monotonic()
    with _census_lock:
        if _census_cache is not None and (now - _census_mono) < _CENSUS_TTL_SEC:
            return _census_cache
    data = _query_census()
    with _census_lock:
        _census_cache = data
        _census_mono = time.monotonic()
        return data


def build_snapshot() -> dict:
    """Cheap host gauges + cached census. Never QueryStats."""
    from app import panel_version
    from app.models.user import UserStatus
    from app.utils.system import (
        cpu_usage,
        disk_usage,
        memory_usage,
        os_uptime,
        realtime_bandwidth,
        realtime_bandwidth_source,
    )

    mem = memory_usage()
    cpu = cpu_usage()
    disk = disk_usage()
    bandwidth = realtime_bandwidth()
    xray_uptime, node_uptime, xray_started, xray_version = _core_uptime()
    census = load_census()
    counts = census.get("counts") or {"total": 0, "by_status": {}}
    by_status = counts.get("by_status") or {}
    return {
        "kind": "tick",
        "t": time.time(),
        "version": panel_version(),
        "online_users": int(census.get("online_users") or 0),
        "users_active": int(by_status.get(UserStatus.active.value, 0) or 0),
        "users_disabled": int(by_status.get(UserStatus.disabled.value, 0) or 0),
        "users_expired": int(by_status.get(UserStatus.expired.value, 0) or 0),
        "users_limited": int(by_status.get(UserStatus.limited.value, 0) or 0),
        "users_on_hold": int(by_status.get(UserStatus.on_hold.value, 0) or 0),
        "total_user": int(counts.get("total") or 0),
        "nodes_connected": int(census.get("nodes_connected") or 0),
        "incoming_bandwidth": int(census.get("uplink") or 0),
        "outgoing_bandwidth": int(census.get("downlink") or 0),
        "incoming_bandwidth_speed": _speed(bandwidth.incoming_bytes),
        "outgoing_bandwidth_speed": _speed(bandwidth.outgoing_bytes),
        "bandwidth_source": realtime_bandwidth_source(),
        "bandwidth_scope": "host",
        "cpu_usage": float(cpu.percent or 0),
        "cpu_cores": int(cpu.cores or 0),
        "mem_used": int(mem.used or 0),
        "mem_total": int(mem.total or 0),
        "disk_used": int(disk.used or 0),
        "disk_total": int(disk.total or 0),
        "os_uptime": int(os_uptime() or 0),
        "xray_uptime": int(xray_uptime or 0),
        "node_uptime": int(node_uptime or 0),
        "xray_started": bool(xray_started),
        "xray_version": xray_version,
        "by_admin": census.get("by_admin") or {},
        "nodes_by_tenant": census.get("nodes_by_tenant") or {},
    }


def publish_tick() -> None:
    try:
        publish_raw(build_snapshot())
    except Exception:
        logger.debug("live tick failed", exc_info=True)


def publish_event(kind: str, payload: Optional[dict] = None) -> None:
    msg = {"kind": kind, "t": time.time()}
    if payload:
        msg.update(payload)
    try:
        publish_raw(msg)
    except Exception:
        logger.debug("live event %s failed", kind, exc_info=True)


def scope_snapshot(
    snap: dict,
    *,
    admin=None,
    dbadmin=None,
    is_sudo: Optional[bool] = None,
    admin_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> dict:
    """Drop other-admin maps; overlay reseller counts. Safe to send to browser."""
    out = {
        k: v
        for k, v in snap.items()
        if k not in ("by_admin", "nodes_by_tenant")
    }
    if is_sudo is None:
        is_sudo = bool(getattr(admin, "is_sudo", False))
    out["incoming_bandwidth_speed"] = _speed(out.get("incoming_bandwidth_speed"))
    out["outgoing_bandwidth_speed"] = _speed(out.get("outgoing_bandwidth_speed"))
    if is_sudo:
        out["bandwidth_scope"] = "host"
        return out

    by_admin = snap.get("by_admin") or {}
    nodes_by_tenant = snap.get("nodes_by_tenant") or {}
    if admin_id is None:
        admin_id = getattr(dbadmin, "id", None)
    if admin_id is None:
        admin_id = getattr(admin, "id", None)
    if tenant_id is None:
        tenant_id = getattr(dbadmin, "tenant_id", None)
    if tenant_id is None:
        tenant_id = getattr(admin, "tenant_id", None)
    scoped = by_admin.get(str(int(admin_id or 0))) or {}
    out["online_users"] = _int(scoped.get("online"))
    out["total_user"] = _int(scoped.get("total"))
    out["users_active"] = _int(scoped.get("users_active"))
    out["users_disabled"] = _int(scoped.get("users_disabled"))
    out["users_expired"] = _int(scoped.get("users_expired"))
    out["users_limited"] = _int(scoped.get("users_limited"))
    out["users_on_hold"] = _int(scoped.get("users_on_hold"))
    if tenant_id is not None:
        out["nodes_connected"] = _int(nodes_by_tenant.get(str(int(tenant_id))))
    else:
        out["nodes_connected"] = 0
    out["bandwidth_scope"] = "scoped_users"
    return out


def snapshot_to_system_stats(scoped: dict):
    from app import panel_version
    from app.models.system import SystemStats

    return SystemStats(
        version=str(scoped.get("version") or panel_version()),
        mem_total=_int(scoped.get("mem_total")),
        mem_used=_int(scoped.get("mem_used")),
        disk_total=_int(scoped.get("disk_total")),
        disk_used=_int(scoped.get("disk_used")),
        cpu_cores=_int(scoped.get("cpu_cores")),
        cpu_usage=_float(scoped.get("cpu_usage")),
        total_user=_int(scoped.get("total_user")),
        online_users=_int(scoped.get("online_users")),
        users_active=_int(scoped.get("users_active")),
        users_disabled=_int(scoped.get("users_disabled")),
        users_expired=_int(scoped.get("users_expired")),
        users_limited=_int(scoped.get("users_limited")),
        users_on_hold=_int(scoped.get("users_on_hold")),
        incoming_bandwidth=_int(scoped.get("incoming_bandwidth")),
        outgoing_bandwidth=_int(scoped.get("outgoing_bandwidth")),
        incoming_bandwidth_speed=_speed(scoped.get("incoming_bandwidth_speed")),
        outgoing_bandwidth_speed=_speed(scoped.get("outgoing_bandwidth_speed")),
        bandwidth_source=str(scoped.get("bandwidth_source") or "nic"),
        os_uptime=_int(scoped.get("os_uptime")),
        xray_uptime=_int(scoped.get("xray_uptime")),
        node_uptime=_int(scoped.get("node_uptime") or scoped.get("xray_uptime")),
    )
