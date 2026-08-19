from typing import List, Union
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.db import Session, crud, get_db
from app.db.models import User
from app.dependencies import validate_dates
from app.models.admin import Admin
from app.models.node import NodesUsageResponse
from app.models.user import UserStatus
from app.utils import responses
from app.utils.system import realtime_bandwidth, realtime_bandwidth_source

router = APIRouter(
    tags=["Analytics"], prefix="/api/analytics", responses={401: responses._401}
)


class TopUser(BaseModel):
    username: str
    used_traffic: int
    status: str


class RealtimeStats(BaseModel):
    online_users: int
    users_active: int
    nodes_connected: int
    incoming_bandwidth_speed: int
    outgoing_bandwidth_speed: int
    bandwidth_source: str = "nic"
    bandwidth_scope: str = "host"


class ProtocolUsageRow(BaseModel):
    protocol: str
    used_traffic: int


_PROTO_USAGE_TTL = 30.0
_proto_usage_cache: dict = {}
_REALTIME_TTL = 1.5
_realtime_cache: dict = {}


@router.get("/usage-by-protocol", response_model=List[ProtocolUsageRow])
def usage_by_protocol(
    start: str = "",
    end: str = "",
    user_id: int | None = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Per-protocol traffic breakdown (scoped to the caller's users)."""
    start, end = validate_dates(start, end)
    admin_id = None
    if not admin.is_sudo:
        dbadmin = crud.get_admin(db, admin.username)
        if not dbadmin:
            raise HTTPException(status_code=404, detail="Admin not found")
        admin_id = dbadmin.id
        if user_id is not None:
            owner = db.query(User).filter(User.id == user_id, User.admin_id == admin_id).first()
            if not owner:
                raise HTTPException(status_code=404, detail="User not found")
    cache_key = (start, end, user_id, admin_id)
    cached = _proto_usage_cache.get(cache_key)
    now = time.monotonic()
    if cached and (now - cached[0]) < _PROTO_USAGE_TTL:
        return cached[1]
    rows = crud.get_protocol_usage(
        db, start, end, user_id=user_id, admin_id=admin_id
    )
    payload = [ProtocolUsageRow(protocol=r["protocol"], used_traffic=r["used_traffic"]) for r in rows]
    _proto_usage_cache[cache_key] = (now, payload)
    if len(_proto_usage_cache) > 64:
        _proto_usage_cache.clear()
        _proto_usage_cache[cache_key] = (now, payload)
    return payload


@router.get("/top-users", response_model=List[TopUser])
def top_users(
    limit: int = 10,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Top users by total consumed traffic (scoped to the admin's users)."""
    limit = max(1, min(limit, 100))
    query = db.query(User)
    if not admin.is_sudo:
        dbadmin = crud.get_admin(db, admin.username)
        query = query.filter(User.admin_id == dbadmin.id)
    rows = query.order_by(User.used_traffic.desc()).limit(limit).all()
    return [
        TopUser(username=u.username, used_traffic=u.used_traffic or 0, status=u.status.value)
        for u in rows
    ]


@router.get("/nodes-usage", response_model=NodesUsageResponse)
def nodes_usage(
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Per-node bandwidth usage time series within a date range."""
    start, end = validate_dates(start, end)
    return {"usages": crud.get_nodes_usage(db, start, end)}


@router.get("/realtime", response_model=RealtimeStats)
def realtime(
    response: Response,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Live snapshot: online users, active users, connected nodes and throughput."""
    from app.models.node import NodeStatus

    response.headers["Cache-Control"] = "no-store"
    cache_key = (int(getattr(admin, "id", 0) or 0), bool(admin.is_sudo))
    cached = _realtime_cache.get(cache_key)
    now = time.monotonic()
    if cached and (now - cached[0]) < _REALTIME_TTL:
        return cached[1]

    dbadmin: Union[Admin, None] = None if admin.is_sudo else crud.get_admin(db, admin.username)
    try:
        from app.sync.live import load_snapshot, scope_snapshot, snapshot_fresh

        snap = load_snapshot()
        if snapshot_fresh(snap):
            scoped = scope_snapshot(
                snap,
                admin=admin,
                dbadmin=dbadmin,
                is_sudo=bool(admin.is_sudo),
                admin_id=int(dbadmin.id) if dbadmin is not None else None,
                tenant_id=(
                    int(dbadmin.tenant_id)
                    if dbadmin is not None and dbadmin.tenant_id is not None
                    else getattr(admin, "tenant_id", None)
                ),
            )
            payload = RealtimeStats(
                online_users=int(scoped.get("online_users") or 0),
                users_active=int(scoped.get("users_active") or 0),
                nodes_connected=int(scoped.get("nodes_connected") or 0),
                incoming_bandwidth_speed=max(0, int(scoped.get("incoming_bandwidth_speed") or 0)),
                outgoing_bandwidth_speed=max(0, int(scoped.get("outgoing_bandwidth_speed") or 0)),
                bandwidth_source=str(scoped.get("bandwidth_source") or "nic"),
                bandwidth_scope=str(scoped.get("bandwidth_scope") or "host"),
            )
            _realtime_cache[cache_key] = (now, payload)
            return payload
    except Exception:
        pass

    bandwidth = realtime_bandwidth()
    nodes = crud.get_nodes(db, status=NodeStatus.connected)
    if not admin.is_sudo and dbadmin:
        nodes = [n for n in nodes if n.tenant_id == dbadmin.tenant_id]

    payload = RealtimeStats(
        online_users=crud.count_online_users(db, admin=dbadmin),
        users_active=crud.get_users_count(db, status=UserStatus.active, admin=dbadmin),
        nodes_connected=len(nodes),
        incoming_bandwidth_speed=max(0, int(bandwidth.incoming_bytes or 0)),
        outgoing_bandwidth_speed=max(0, int(bandwidth.outgoing_bytes or 0)),
        bandwidth_source=realtime_bandwidth_source(),
        bandwidth_scope="host" if admin.is_sudo else "scoped_users",
    )
    _realtime_cache[cache_key] = (now, payload)
    return payload
