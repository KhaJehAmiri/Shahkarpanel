import asyncio
import hmac
import time
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.websockets import WebSocketDisconnect

from app import logger, xray
from app.bootstrap_limit import enforce_bootstrap_rate_limit
from app.db import Session, crud, get_db
from app.dependencies import get_dbnode, get_scoped_node, validate_dates
from app.events import EventType, publish
from app.models.admin import Admin
from app.models.node import (
    NodeCreate,
    NodeGroupCreate,
    NodeGroupResponse,
    NodeModify,
    NodeResponse,
    NodeSettings,
    NodeStatus,
    NodesUsageResponse,
)
from app.models.proxy import ProxyHost
from app.rbac import require_permission
from app.utils import responses
from app.utils.ws_auth import ws_bearer_token
from config import (
    NODE_BOOTSTRAP_MAX_ATTEMPTS,
    NODE_BOOTSTRAP_TOKEN,
    NODE_BOOTSTRAP_WINDOW_SECONDS,
)


class NodeBootstrap(BaseModel):
    token: str
    name: str
    address: str
    port: int = 62050
    api_port: int = 62051
    region: Optional[str] = None
    group_id: Optional[int] = None
    # Phase 6: white-label / topology metadata supplied by the install command.
    tenant_id: Optional[int] = None
    role: Optional[str] = "direct"
    core_kind: Optional[str] = "xray"


class NodeBootstrapResponse(BaseModel):
    node: NodeResponse
    certificate: str

router = APIRouter(
    tags=["Node"], prefix="/api", responses={401: responses._401, 403: responses._403}
)


def add_host_if_needed(new_node: NodeCreate, db: Session):
    """Add a host if specified in the new node settings."""
    if new_node.add_as_new_host:
        host = ProxyHost(
            remark=f"{new_node.name} ({{USERNAME}}) [{{PROTOCOL}} - {{TRANSPORT}}]",
            address=new_node.address,
        )
        for inbound_tag in xray.config.inbounds_by_tag:
            crud.add_host(db, inbound_tag, host)
        xray.hosts.update()


@router.get("/node/settings", response_model=NodeSettings)
def get_node_settings(
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Retrieve the current node settings, including TLS certificate."""
    tls = crud.get_tls_certificate(db)
    return NodeSettings(certificate=tls.certificate)


@router.post("/node/bootstrap", response_model=NodeBootstrapResponse,
             responses={403: responses._403, 409: responses._409})
def bootstrap_node(
    request: Request,
    body: NodeBootstrap,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Self-register a node using a shared bootstrap token (auto-discovery).

    Disabled unless NODE_BOOTSTRAP_TOKEN is set. Returns the panel TLS
    certificate the node needs to trust incoming control connections.
    """
    enforce_bootstrap_rate_limit(
        request,
        max_attempts=NODE_BOOTSTRAP_MAX_ATTEMPTS,
        window_seconds=NODE_BOOTSTRAP_WINDOW_SECONDS,
    )
    if not NODE_BOOTSTRAP_TOKEN or not hmac.compare_digest(body.token, NODE_BOOTSTRAP_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid or disabled bootstrap token")

    if body.core_kind and body.core_kind not in ("xray", "wireguard"):
        raise HTTPException(status_code=422, detail="invalid core_kind")

    from app.db.models import Node as DBNode
    from app.models.node import CoreKind
    from app.provisioning import jobs as provision_jobs

    pending = db.query(DBNode).filter(
        DBNode.name == body.name,
        DBNode.provision_status.in_(("provisioning", "failed")),
    ).first()

    if pending:
        pending.address = body.address
        pending.port = body.port
        pending.api_port = body.api_port
        if body.region:
            pending.region = body.region
        if body.group_id is not None:
            pending.group_id = body.group_id
        pending.provision_status = "registered"
        pending.provision_host = body.address
        pending.provision_message = None
        if body.tenant_id is not None:
            pending.tenant_id = body.tenant_id
        if body.role:
            pending.role = body.role
        db.commit()
        db.refresh(pending)
        dbnode = pending
        provision_jobs.complete_for_node(pending.id)
    else:
        try:
            dbnode = crud.create_node(
                db,
                NodeCreate(
                    name=body.name,
                    address=body.address,
                    port=body.port,
                    api_port=body.api_port,
                    region=body.region,
                    group_id=body.group_id,
                    core_kind=CoreKind(body.core_kind or "xray"),
                ),
            )
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail=f'Node "{body.name}" already exists')

        if body.tenant_id is not None or (body.role and body.role != "direct"):
            if body.role and body.role not in ("direct", "relay", "exit"):
                raise HTTPException(status_code=422, detail="invalid node role")
            if body.tenant_id is not None:
                from app.db.models import Tenant
                if db.query(Tenant.id).filter(Tenant.id == body.tenant_id).first() is None:
                    raise HTTPException(status_code=422, detail="Unknown tenant_id")
            dbnode.tenant_id = body.tenant_id
            if body.role:
                dbnode.role = body.role
            dbnode.provision_status = "registered"
            dbnode.provision_host = body.address
            db.commit()
            db.refresh(dbnode)

    if dbnode.core_kind == CoreKind.wireguard.value:
        crud.provision_wireguard_defaults(db, dbnode)

    bg.add_task(xray.operations.connect_node, node_id=dbnode.id)
    tls = crud.get_tls_certificate(db)

    publish(EventType.node_created, {"node_id": dbnode.id, "name": dbnode.name, "via": "bootstrap"})
    logger.info(f'Node "{dbnode.name}" self-registered via bootstrap')
    return NodeBootstrapResponse(node=dbnode, certificate=tls.certificate)


@router.get("/node/groups", response_model=List[NodeGroupResponse])
def get_node_groups(db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)):
    """List node groups."""
    return crud.get_node_groups(db)


@router.post("/node/groups", response_model=NodeGroupResponse, responses={409: responses._409})
def add_node_group(
    body: NodeGroupCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Create a node group."""
    try:
        return crud.create_node_group(db, name=body.name, region=body.region)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Group "{body.name}" already exists')


@router.delete("/node/groups/{group_id}")
def delete_node_group(
    group_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Delete a node group."""
    group = crud.get_node_group_by_id(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    crud.remove_node_group(db, group)
    return {}


@router.post("/node", response_model=NodeResponse, responses={409: responses._409})
def add_node(
    new_node: NodeCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Add a new node to the database and optionally add it as a host."""
    try:
        dbnode = crud.create_node(db, new_node)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f'Node "{new_node.name}" already exists'
        )

    bg.add_task(xray.operations.connect_node, node_id=dbnode.id)
    bg.add_task(add_host_if_needed, new_node, db)

    publish(EventType.node_created, {"node_id": dbnode.id, "name": dbnode.name})
    logger.info(f'New node "{dbnode.name}" added')
    return dbnode


@router.get("/node/{node_id}", response_model=NodeResponse)
def get_node(
    dbnode: NodeResponse = Depends(get_dbnode),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Retrieve details of a specific node by its ID."""
    return dbnode


@router.websocket("/node/{node_id}/logs")
async def node_logs(node_id: int, websocket: WebSocket, db: Session = Depends(get_db)):
    token = ws_bearer_token(websocket)
    admin = Admin.get_admin(token, db)
    if not admin:
        return await websocket.close(reason="Unauthorized", code=4401)

    if not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    if not xray.nodes.get(node_id):
        return await websocket.close(reason="Node not found", code=4404)

    if not xray.nodes[node_id].connected:
        return await websocket.close(reason="Node is not connected", code=4400)

    interval = websocket.query_params.get("interval")
    if interval:
        try:
            interval = float(interval)
        except ValueError:
            return await websocket.close(reason="Invalid interval value", code=4400)
        if interval > 10:
            return await websocket.close(
                reason="Interval must be more than 0 and at most 10 seconds", code=4400
            )

    await websocket.accept()

    cache = ""
    last_sent_ts = 0
    node = xray.nodes[node_id]
    with node.get_logs() as logs:
        while True:
            if not node == xray.nodes[node_id]:
                break

            if interval and time.time() - last_sent_ts >= interval and cache:
                try:
                    await websocket.send_text(cache)
                except (WebSocketDisconnect, RuntimeError):
                    break
                cache = ""
                last_sent_ts = time.time()

            if not logs:
                try:
                    await asyncio.wait_for(websocket.receive(), timeout=0.2)
                    continue
                except asyncio.TimeoutError:
                    continue
                except (WebSocketDisconnect, RuntimeError):
                    break

            log = logs.popleft()

            if interval:
                cache += f"{log}\n"
                continue

            try:
                await websocket.send_text(log)
            except (WebSocketDisconnect, RuntimeError):
                break


@router.get("/nodes", response_model=List[NodeResponse])
def get_nodes(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("nodes:read")),
):
    """List nodes. Sudo sees all; resellers see only their workspace."""
    from app.provisioning import jobs as provision_jobs
    from app.tenant.reseller_ops import list_scoped_nodes

    out: List[NodeResponse] = []
    for dbnode in list_scoped_nodes(db, admin):
        row = NodeResponse.model_validate(dbnode)
        job = provision_jobs.progress_for_node(dbnode.id)
        if job:
            row.provision_progress = job.progress
            row.provision_step = job.step
            if job.message:
                row.provision_message = job.message
        elif row.provision_status == "provisioning":
            row.provision_progress = row.provision_progress or 5
            row.provision_step = row.provision_step or "queued"
        out.append(row)
    return out


@router.put("/node/{node_id}", response_model=NodeResponse)
def modify_node(
    modified_node: NodeModify,
    bg: BackgroundTasks,
    dbnode: NodeResponse = Depends(get_node),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Update a node's details. Only accessible to sudo admins."""
    updated_node = crud.update_node(db, dbnode, modified_node)
    xray.operations.remove_node(updated_node.id)
    if updated_node.status != NodeStatus.disabled:
        bg.add_task(xray.operations.connect_node, node_id=updated_node.id)

    publish(EventType.node_modified, {"node_id": updated_node.id, "name": updated_node.name})
    logger.info(f'Node "{dbnode.name}" modified')
    return dbnode


class AmneziaWGConfig(BaseModel):
    """AmneziaWG obfuscation parameters. All optional; null clears a field."""
    awg_jc: Optional[int] = None
    awg_jmin: Optional[int] = None
    awg_jmax: Optional[int] = None
    awg_s1: Optional[int] = None
    awg_s2: Optional[int] = None
    awg_h1: Optional[int] = None
    awg_h2: Optional[int] = None
    awg_h3: Optional[int] = None
    awg_h4: Optional[int] = None


class SingBoxNodeConfig(BaseModel):
    certificate_path: Optional[str] = None
    key_path: Optional[str] = None
    sni: Optional[str] = None
    clash_api_port: Optional[int] = None
    clash_api_secret: Optional[str] = None
    hysteria2_enabled: Optional[bool] = None
    hysteria2_port: Optional[int] = None
    hysteria2_up_mbps: Optional[int] = None
    hysteria2_down_mbps: Optional[int] = None
    hysteria2_obfs_password: Optional[str] = None
    tuic_enabled: Optional[bool] = None
    tuic_port: Optional[int] = None
    tuic_congestion_control: Optional[str] = None


@router.put("/node/{node_id}/singbox", response_model=NodeResponse)
def set_node_singbox(
    body: SingBoxNodeConfig,
    bg: BackgroundTasks,
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Configure Hysteria2/TUIC on a normal Xray node (sudo only).

    sing-box runs alongside Xray on the node agent; enabling a protocol here
    provisions the inbound and pushes the user list on save.
    """
    from app.models.node import CoreKind

    if dbnode.core_kind == CoreKind.wireguard.value:
        raise HTTPException(status_code=400, detail="WireGuard nodes cannot run sing-box")
    crud.upsert_node_singbox(db, dbnode, **body.model_dump(exclude_unset=True))
    db.refresh(dbnode)
    bg.add_task(_sync_singbox_node, dbnode.id)
    return dbnode


def _sync_singbox_node(node_id: int) -> None:
    try:
        from app.db import GetDB
        from app.singbox.operations import sync_node

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode:
                sync_node(db, dbnode)
    except Exception:
        pass


@router.put("/node/{node_id}/amneziawg", response_model=NodeResponse)
def set_node_amneziawg(
    body: AmneziaWGConfig,
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Configure AmneziaWG obfuscation on a WireGuard node (sudo only).

    Turns a plain WireGuard node into an obfuscated AmneziaWG node; client
    configs then emit the Jc/Jmin/Jmax/S1/S2/H1–H4 parameters under [Interface].
    """
    from app.models.node import CoreKind

    if dbnode.core_kind != CoreKind.wireguard.value:
        raise HTTPException(status_code=400, detail="Node is not a WireGuard node")
    try:
        crud.set_node_amnezia(db, dbnode, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return dbnode


@router.post("/node/{node_id}/reconnect")
def reconnect_node(
    bg: BackgroundTasks,
    dbnode=Depends(get_scoped_node),
    _: Admin = Depends(require_permission("nodes:provision")),
):
    """Trigger a reconnection for a node in the caller's workspace."""
    bg.add_task(xray.operations.connect_node, node_id=dbnode.id)
    return {"detail": "Reconnection task scheduled"}


@router.delete("/node/{node_id}")
def remove_node(
    dbnode=Depends(get_scoped_node),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("nodes:provision")),
):
    """Delete an owned node and remove it from xray in the background."""
    crud.remove_node(db, dbnode)
    xray.operations.remove_node(dbnode.id)

    publish(EventType.node_deleted, {"node_id": dbnode.id, "name": dbnode.name})
    logger.info(f'Node "{dbnode.name}" deleted')
    return {}


@router.get("/nodes/usage", response_model=NodesUsageResponse)
def get_usage(
    db: Session = Depends(get_db),
    start: str = "",
    end: str = "",
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Retrieve usage statistics for nodes within a specified date range."""
    start, end = validate_dates(start, end)

    usages = crud.get_nodes_usage(db, start, end)

    return {"usages": usages}
