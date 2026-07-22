from typing import List, Union

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
    rows = crud.get_protocol_usage(
        db, start, end, user_id=user_id, admin_id=admin_id
    )
    return [ProtocolUsageRow(protocol=r["protocol"], used_traffic=r["used_traffic"]) for r in rows]


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
    dbadmin: Union[Admin, None] = None if admin.is_sudo else crud.get_admin(db, admin.username)
    bandwidth = realtime_bandwidth()
    nodes = crud.get_nodes(db, status=NodeStatus.connected)
    if not admin.is_sudo and dbadmin:
        nodes = [n for n in nodes if n.tenant_id == dbadmin.tenant_id]

    return RealtimeStats(
        online_users=crud.count_online_users(db, admin=dbadmin),
        users_active=crud.get_users_count(db, status=UserStatus.active, admin=dbadmin),
        nodes_connected=len(nodes),
        incoming_bandwidth_speed=bandwidth.incoming_bytes,
        outgoing_bandwidth_speed=bandwidth.outgoing_bytes,
        bandwidth_source=realtime_bandwidth_source(),
        bandwidth_scope="host" if admin.is_sudo else "scoped_users",
    )
