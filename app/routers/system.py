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
from app.utils.system import cpu_usage, memory_usage, realtime_bandwidth, realtime_bandwidth_source

router = APIRouter(tags=["System"], prefix="/api", responses={401: responses._401})


@router.get("/system", response_model=SystemStats)
def get_system_stats(
    response: Response,
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.get_current)
):
    """Fetch system stats including memory, CPU, and user metrics."""
    response.headers["Cache-Control"] = "no-store"
    mem = memory_usage()
    cpu = cpu_usage()
    system = crud.get_system_usage(db)
    dbadmin: Union[Admin, None] = crud.get_admin(db, admin.username)

    total_user = crud.get_users_count(db, admin=dbadmin if not admin.is_sudo else None)
    users_active = crud.get_users_count(
        db, status=UserStatus.active, admin=dbadmin if not admin.is_sudo else None
    )
    users_disabled = crud.get_users_count(
        db, status=UserStatus.disabled, admin=dbadmin if not admin.is_sudo else None
    )
    users_on_hold = crud.get_users_count(
        db, status=UserStatus.on_hold, admin=dbadmin if not admin.is_sudo else None
    )
    users_expired = crud.get_users_count(
        db, status=UserStatus.expired, admin=dbadmin if not admin.is_sudo else None
    )
    users_limited = crud.get_users_count(
        db, status=UserStatus.limited, admin=dbadmin if not admin.is_sudo else None
    )
    online_users = crud.count_online_users(
        db, 24, admin=dbadmin if not admin.is_sudo else None
    )
    realtime_bandwidth_stats = realtime_bandwidth()

    return SystemStats(
        version=panel_version(),
        mem_total=mem.total,
        mem_used=mem.used,
        cpu_cores=cpu.cores,
        cpu_usage=cpu.percent,
        total_user=total_user,
        online_users=online_users,
        users_active=users_active,
        users_disabled=users_disabled,
        users_expired=users_expired,
        users_limited=users_limited,
        users_on_hold=users_on_hold,
        incoming_bandwidth=system.uplink,
        outgoing_bandwidth=system.downlink,
        incoming_bandwidth_speed=realtime_bandwidth_stats.incoming_bytes,
        outgoing_bandwidth_speed=realtime_bandwidth_stats.outgoing_bytes,
        bandwidth_source=realtime_bandwidth_source(),
    )


@router.get("/inbounds")
def get_inbounds(admin: Admin = Depends(Admin.get_current)) -> Dict[str, List[dict]]:
    """Retrieve inbound configurations grouped by protocol.

    Uses plain dicts so the synthetic ``amneziawg`` bucket (Xray wireguard
    listeners on the panel master) serializes without enum validation errors.
    """
    return {key: list(items) for key, items in xray.config.inbounds_by_protocol.items()}


@router.get(
    "/hosts", response_model=Dict[str, List[ProxyHost]], responses={403: responses._403}
)
def get_hosts(
    db: Session = Depends(get_db), admin: Admin = Depends(require_permission("hosts:read"))
):
    """Get a list of proxy hosts grouped by inbound tag."""
    hosts = {tag: crud.get_hosts(db, tag) for tag in xray.config.inbounds_by_tag}
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
    for inbound_tag in modified_hosts:
        if inbound_tag not in xray.config.inbounds_by_tag:
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

    return {tag: crud.get_hosts(db, tag) for tag in xray.config.inbounds_by_tag}


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
    if body.source_tag not in xray.config.inbounds_by_tag:
        raise HTTPException(status_code=404, detail="Source inbound not found")
    source = crud.get_hosts(db, body.source_tag)
    if not source:
        raise HTTPException(status_code=404, detail="Source inbound has no hosts")
    cloned = 0
    for tag in body.target_tags:
        if tag not in xray.config.inbounds_by_tag:
            continue
        if body.mode == "replace":
            crud.update_hosts(db, tag, [])
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
