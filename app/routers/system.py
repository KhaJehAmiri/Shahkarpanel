import time
from typing import Dict, List, Union

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app import logger, panel_version, xray
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.models.proxy import ProxyHost
from app.models.system import SystemStats
from app.models.user import UserStatus
from app.rbac import require_permission
from app.utils import responses
from app.utils.system import (
    cpu_usage,
    disk_usage,
    memory_usage,
    os_uptime,
    realtime_bandwidth,
    realtime_bandwidth_source,
)

router = APIRouter(tags=["System"], prefix="/api", responses={401: responses._401})

_SYSTEM_STATS_TTL = 2.0
_system_stats_cache: dict = {}


@router.get("/system", response_model=SystemStats)
def get_system_stats(
    response: Response,
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.get_current)
):
    """Fetch system stats including memory, CPU, and user metrics."""
    response.headers["Cache-Control"] = "no-store"
    cache_key = (int(getattr(admin, "id", 0) or 0), bool(admin.is_sudo))
    cached = _system_stats_cache.get(cache_key)
    now = time.monotonic()
    if cached and (now - cached[0]) < _SYSTEM_STATS_TTL:
        return cached[1]

    dbadmin: Union[Admin, None] = crud.get_admin(db, admin.username)
    try:
        from app.sync.live import (
            load_snapshot,
            scope_snapshot,
            snapshot_fresh,
            snapshot_to_system_stats,
        )

        snap = load_snapshot()
        if snapshot_fresh(snap):
            scoped = scope_snapshot(
                snap,
                admin=admin,
                dbadmin=None if admin.is_sudo else dbadmin,
                is_sudo=bool(admin.is_sudo),
                admin_id=int(dbadmin.id) if dbadmin is not None and not admin.is_sudo else None,
                tenant_id=(
                    int(dbadmin.tenant_id)
                    if dbadmin is not None and dbadmin.tenant_id is not None
                    else getattr(admin, "tenant_id", None)
                ),
            )
            stats = snapshot_to_system_stats(scoped)
            _system_stats_cache[cache_key] = (now, stats)
            return stats
    except Exception:
        pass

    mem = memory_usage()
    cpu = cpu_usage()
    disk = disk_usage()
    system = crud.get_system_usage(db)

    xray_started_at = getattr(xray.core, "started_at", None)
    xray_uptime = int(time.time() - xray_started_at) if xray_started_at else 0
    # API process has an empty xray.nodes map; node_uptime comes from the
    # worker snapshot above. Fallback stays 0 rather than walking a lie.
    node_uptime = 0
    scope_admin = dbadmin if not admin.is_sudo else None
    counts = crud.get_user_status_counts(db, admin=scope_admin)
    by_status = counts.get("by_status") or {}
    online_users = crud.count_online_users(db, admin=scope_admin)
    realtime_bandwidth_stats = realtime_bandwidth()

    stats = SystemStats(
        version=panel_version(),
        mem_total=mem.total,
        mem_used=mem.used,
        disk_total=disk.total,
        disk_used=disk.used,
        cpu_cores=cpu.cores,
        cpu_usage=cpu.percent,
        total_user=counts.get("total") or 0,
        online_users=online_users,
        users_active=by_status.get(UserStatus.active.value, 0),
        users_disabled=by_status.get(UserStatus.disabled.value, 0),
        users_expired=by_status.get(UserStatus.expired.value, 0),
        users_limited=by_status.get(UserStatus.limited.value, 0),
        users_on_hold=by_status.get(UserStatus.on_hold.value, 0),
        incoming_bandwidth=system.uplink,
        outgoing_bandwidth=system.downlink,
        incoming_bandwidth_speed=max(0, int(realtime_bandwidth_stats.incoming_bytes or 0)),
        outgoing_bandwidth_speed=max(0, int(realtime_bandwidth_stats.outgoing_bytes or 0)),
        bandwidth_source=realtime_bandwidth_source(),
        os_uptime=os_uptime(),
        xray_uptime=xray_uptime,
        node_uptime=node_uptime,
    )
    _system_stats_cache[cache_key] = (now, stats)
    return stats


@router.get("/system/online-presence", responses={403: responses._403})
def get_online_presence(
    db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)
) -> dict:
    """Diagnostics for the "online now" counter.

    ``tracker.age`` is the seconds since the presence thread last ran; anything
    much above ``tracker.interval`` means the counter is going stale and the
    thread (not a scheduler job) is the thing to look at.
    """
    from datetime import datetime

    from sqlalchemy import func

    from app.db.models import User
    from app.presence import presence_health
    from config import ONLINE_WINDOW_MINUTES

    latest = db.query(func.max(User.online_at)).scalar()
    return {
        "tracker": presence_health(),
        "window_minutes": ONLINE_WINDOW_MINUTES,
        "online_users": crud.count_online_users(db),
        "last_seen_seconds_ago": (
            round((datetime.utcnow() - latest).total_seconds(), 1) if latest else None
        ),
    }


@router.get("/inbounds")
def get_inbounds(admin: Admin = Depends(Admin.get_current)) -> Dict[str, List[dict]]:
    """Retrieve inbound configurations grouped by protocol.

    Uses plain dicts so the synthetic ``amneziawg`` bucket (Xray wireguard
    listeners on the panel master) serializes without enum validation errors.
    """
    return {key: list(items) for key, items in xray.config.inbounds_by_protocol.items()}


class AssignableNativeProtocols(BaseModel):
    wireguard: bool = False
    amneziawg: bool = False
    hysteria2: bool = False
    tuic: bool = False
    anytls: bool = False


@router.get("/assignable-native-protocols", response_model=AssignableNativeProtocols)
def get_assignable_native_protocols(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Native protocols the caller may assign when creating/editing users.

    Includes the shared main-panel fleet for resellers (not only workspace-owned
    nodes), so toggles match what is active on the owner panel.
    """
    from app.tenant.reseller_ops import assignable_native_protocols

    return AssignableNativeProtocols(**assignable_native_protocols(db, admin))


def _host_tags() -> list[str]:
    from app.subscription.host_buckets import host_bucket_tags

    return host_bucket_tags(xray.config.inbounds_by_tag)


@router.get(
    "/hosts", response_model=Dict[str, List[ProxyHost]], responses={403: responses._403}
)
def get_hosts(
    db: Session = Depends(get_db), admin: Admin = Depends(require_permission("hosts:read"))
):
    """Get a list of proxy hosts grouped by inbound tag (incl. native WG/H2/…)."""
    from app.subscription.host_buckets import is_native_host_tag

    hosts = {}
    for tag in _host_tags():
        if is_native_host_tag(tag):
            hosts[tag] = crud.get_hosts_existing(db, tag)
        else:
            hosts[tag] = crud.get_hosts(db, tag)
    return hosts


@router.get("/hosts/region-presets", responses={403: responses._403})
def get_host_region_presets(
    admin: Admin = Depends(require_permission("hosts:read")),
):
    """Region codes for host remark flags (works without binding a node)."""
    from app.subscription.region_display import list_region_presets

    return {"regions": list_region_presets()}


@router.put(
    "/hosts", response_model=Dict[str, List[ProxyHost]], responses={403: responses._403}
)
def modify_hosts(
    modified_hosts: Dict[str, List[ProxyHost]],
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("hosts:write")),
):
    """Modify proxy hosts and update the configuration."""
    from app.subscription.host_buckets import is_native_host_tag

    allowed = set(_host_tags())
    for inbound_tag in modified_hosts:
        if inbound_tag not in allowed:
            raise HTTPException(
                status_code=400, detail=f"Inbound {inbound_tag} doesn't exist"
            )

    for inbound_tag, hosts in modified_hosts.items():
        crud.update_hosts(db, inbound_tag, hosts)

    xray.hosts.update()

    from app.services.edge_proxy import cdn_runtime_enabled, sync_edge_nginx

    try:
        edge_result = sync_edge_nginx(db)
        if edge_result.routes or cdn_runtime_enabled():
            startup_config = xray.config.include_db_users()
            xray.core.restart(startup_config)
    except Exception as exc:
        logger.exception("edge sync failed (hosts saved): %s", exc)

    # Return same shape as GET (native tags included; empty until configured).
    out = {}
    for tag in _host_tags():
        if is_native_host_tag(tag):
            out[tag] = crud.get_hosts_existing(db, tag)
        else:
            out[tag] = crud.get_hosts(db, tag)
    return out


class HostCloneBody(BaseModel):
    source_tag: str
    target_tags: List[str]
    mode: str = "append"  # append | replace


@router.post("/hosts/clone", responses={403: responses._403})
def clone_hosts(
    body: HostCloneBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("hosts:write")),
):
    """Clone host rows from one inbound to others (bulk template)."""
    from app.subscription.host_buckets import is_native_host_tag

    allowed = set(_host_tags())
    if body.source_tag not in allowed:
        raise HTTPException(status_code=404, detail="Source inbound not found")
    if is_native_host_tag(body.source_tag):
        source = crud.get_hosts_existing(db, body.source_tag)
    else:
        source = crud.get_hosts(db, body.source_tag)
    if not source:
        raise HTTPException(status_code=404, detail="Source inbound has no hosts")
    cloned = 0
    for tag in body.target_tags:
        if tag not in allowed:
            continue
        if body.mode == "replace":
            crud.update_hosts(db, tag, [])
        if is_native_host_tag(tag):
            existing = crud.get_hosts_existing(db, tag)
        else:
            existing = crud.get_hosts(db, tag)
        merged = list(existing) + [h.model_copy(deep=True) for h in source]
        crud.update_hosts(db, tag, merged)
        cloned += len(source)
    xray.hosts.update()
    return {"cloned": cloned, "targets": body.target_tags}


@router.post("/system/jwt/rotate")
def rotate_jwt_secret(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Rotate subscription JWT signing secret (invalidates existing sub links)."""
    import secrets

    from app.db.models import JWT
    from app.utils.jwt import clear_secret_key_cache

    row = db.query(JWT).first()
    key = secrets.token_urlsafe(32)
    if row is None:
        db.add(JWT(secret_key=key))
    else:
        row.secret_key = key
    db.commit()
    clear_secret_key_cache()
    return {"detail": "JWT secret rotated; users must refresh subscription links"}
