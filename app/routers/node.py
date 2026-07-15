import asyncio
import hmac
import time
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from starlette.websockets import WebSocketDisconnect

from app import logger, xray
from app.bootstrap_limit import enforce_bootstrap_rate_limit
from app.services.node_register import (
    apply_bootstrap_metadata,
    connect_node_async,
    create_node_record,
    finalize_new_node,
)
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
    NodeWarpSettings,
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
            dbnode = create_node_record(
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
            if body.role and body.role not in ("direct", "relay", "transit", "exit"):
                raise HTTPException(status_code=422, detail="invalid node role")
            if body.tenant_id is not None:
                from app.db.models import Tenant
                if db.query(Tenant.id).filter(Tenant.id == body.tenant_id).first() is None:
                    raise HTTPException(status_code=422, detail="Unknown tenant_id")
            apply_bootstrap_metadata(
                db,
                dbnode,
                tenant_id=body.tenant_id,
                role=body.role,
                address=body.address,
            )

    finalize_new_node(db, dbnode)

    connect_node_async(bg, dbnode.id)
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
        dbnode = create_node_record(db, new_node)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f'Node "{new_node.name}" already exists'
        )

    finalize_new_node(db, dbnode)

    connect_node_async(bg, dbnode.id)
    from app.services.materialize import provision_slug_list
    from app.services.node_apply import set_node_services

    default_slugs = provision_slug_list(
        core_kind=new_node.core_kind.value if hasattr(new_node.core_kind, "value") else str(new_node.core_kind),
        enable_plain_wg=new_node.core_kind.value == "wireguard" if hasattr(new_node.core_kind, "value") else False,
        enable_xray=new_node.core_kind.value == "xray" if hasattr(new_node.core_kind, "value") else True,
    )
    if default_slugs:
        set_node_services(db, dbnode, default_slugs, replace=True)
    elif new_node.add_as_new_host:
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
    return NodeResponse.model_validate(updated_node)


class AmneziaWGConfig(BaseModel):
    """AmneziaWG obfuscation parameters. All optional; null clears a field."""
    awg_jc: Optional[int] = None
    awg_jmin: Optional[int] = None
    awg_jmax: Optional[int] = None
    awg_s1: Optional[int] = None
    awg_s2: Optional[int] = None
    awg_s3: Optional[int] = None
    awg_s4: Optional[int] = None
    awg_h1: Optional[int] = None
    awg_h2: Optional[int] = None
    awg_h3: Optional[int] = None
    awg_h4: Optional[int] = None


class SgWireConfig(BaseModel):
    enabled: bool


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
    anytls_enabled: Optional[bool] = None
    anytls_port: Optional[int] = None


@router.put("/node/{node_id}/singbox", response_model=NodeResponse)
def set_node_singbox(
    body: SingBoxNodeConfig,
    bg: BackgroundTasks,
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Configure Hysteria2/TUIC/AnyTLS on a node (sudo only).

    sing-box runs alongside Xray or native WireGuard on the node agent; enabling
    a protocol here provisions the inbound and pushes the user list on save.
    """
    crud.upsert_node_singbox(db, dbnode, **body.model_dump(exclude_unset=True))
    db.refresh(dbnode)
    bg.add_task(_sync_singbox_node, dbnode.id)
    return dbnode


def _sync_singbox_node(node_id: int) -> bool:
    from app import logger

    try:
        from app.db import GetDB
        from app.singbox.operations import sync_node

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if not dbnode:
                logger.warning("sing-box sync skipped: node %s not found", node_id)
                return False
            sync_node(db, dbnode)
            return True
    except Exception as exc:
        logger.exception("sing-box sync failed for node %s: %s", node_id, exc)
        return False


@router.post("/node/{node_id}/singbox/sync")
def sync_singbox_now(
    dbnode=Depends(get_dbnode),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Push the current sing-box spec to the node immediately (awaited)."""
    ok = _sync_singbox_node(dbnode.id)
    if not ok:
        raise HTTPException(status_code=502, detail="sing-box sync failed — see panel logs")
    return {"synced": True}


class SingBoxTLSStatus(BaseModel):
    present: bool = False
    trusted: bool = False
    issuer: Optional[str] = None
    expires_at: Optional[str] = None
    tls_le_domain: Optional[str] = None
    tls_le_kind: Optional[str] = None


class SingBoxTLSIssueBody(BaseModel):
    email: str
    domain: Optional[str] = None
    identifier: Optional[str] = None
    tls_kind: str = "auto"
    ssh_username: str = "root"
    ssh_password: Optional[str] = None
    ssh_port: int = 22

    def resolved_target(self) -> str:
        target = (self.identifier or self.domain or "").strip()
        if not target:
            raise ValueError("identifier or domain is required")
        return target


class SingBoxTLSRenewBody(BaseModel):
    ssh_username: str = "root"
    ssh_password: Optional[str] = None
    ssh_port: int = 22


@router.get("/node/{node_id}/singbox/tls/status", response_model=SingBoxTLSStatus)
def get_singbox_tls_status(
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Return cached TLS metadata; refresh from the live node when connected."""
    from app.singbox.tls import refresh_node_tls

    cfg = dbnode.singbox
    if cfg is None:
        return SingBoxTLSStatus()
    try:
        status = refresh_node_tls(db, dbnode)
    except Exception:
        status = {}
    return SingBoxTLSStatus(
        present=bool(status.get("present")),
        trusted=bool(cfg.tls_trusted),
        issuer=cfg.tls_issuer,
        expires_at=status.get("expires_at") or (
            cfg.tls_expires_at.isoformat() if cfg.tls_expires_at else None
        ),
        tls_le_domain=cfg.tls_le_domain,
        tls_le_kind=cfg.tls_le_kind,
    )


@router.post("/node/{node_id}/singbox/tls/issue", response_model=SingBoxTLSStatus)
def issue_singbox_tls(
    body: SingBoxTLSIssueBody,
    bg: BackgroundTasks,
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Obtain a Let's Encrypt cert on the node host over SSH and sync sing-box."""
    from app.provisioning import ProvisioningError, ProvisioningUnavailable, SSHCredentials
    from app.singbox.tls import refresh_node_tls
    from app.tls.acme import DEFAULT_CERT, DEFAULT_KEY, issue_certificate, normalize_tls_target

    if dbnode.singbox is None:
        raise HTTPException(status_code=400, detail="Configure sing-box on this node first")
    if not body.ssh_password:
        raise HTTPException(status_code=422, detail="ssh_password is required for remote issuance")
    try:
        target = body.resolved_target()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    creds = SSHCredentials(
        host=dbnode.address,
        port=body.ssh_port,
        username=body.ssh_username,
        password=body.ssh_password,
    )
    cert_path = dbnode.singbox.certificate_path or DEFAULT_CERT
    key_path = dbnode.singbox.key_path or DEFAULT_KEY
    try:
        identifier, kind = normalize_tls_target(target, body.tls_kind)
        issue_certificate(
            creds,
            identifier,
            body.email.strip(),
            tls_kind=kind,
            cert_path=cert_path,
            key_path=key_path,
        )
    except ProvisioningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProvisioningError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    crud.upsert_node_singbox(
        db,
        dbnode,
        sni=identifier,
        tls_le_domain=identifier,
        tls_le_kind=kind,
        certificate_path=cert_path,
        key_path=key_path,
    )
    db.refresh(dbnode)
    try:
        status = refresh_node_tls(db, dbnode)
    except Exception:
        status = {"present": True, "trusted": True}
    bg.add_task(_sync_singbox_node, dbnode.id)
    return SingBoxTLSStatus(
        present=bool(status.get("present", True)),
        trusted=bool(dbnode.singbox.tls_trusted),
        issuer=dbnode.singbox.tls_issuer,
        expires_at=status.get("expires_at"),
        tls_le_domain=dbnode.singbox.tls_le_domain,
        tls_le_kind=dbnode.singbox.tls_le_kind,
    )


@router.post("/node/{node_id}/singbox/tls/renew", response_model=SingBoxTLSStatus)
def renew_singbox_tls(
    body: SingBoxTLSRenewBody,
    bg: BackgroundTasks,
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Renew an existing Let's Encrypt cert on the node (domain or IP)."""
    from app.provisioning import ProvisioningError, ProvisioningUnavailable, SSHCredentials
    from app.singbox.tls import refresh_node_tls
    from app.tls.acme import DEFAULT_CERT, DEFAULT_KEY, renew_certificate

    cfg = dbnode.singbox
    if cfg is None:
        raise HTTPException(status_code=400, detail="Configure sing-box on this node first")
    if not cfg.tls_le_domain:
        raise HTTPException(status_code=400, detail="No LE target recorded — issue a certificate first")
    if not body.ssh_password:
        raise HTTPException(status_code=422, detail="ssh_password is required for remote renewal")

    creds = SSHCredentials(
        host=dbnode.address,
        port=body.ssh_port,
        username=body.ssh_username,
        password=body.ssh_password,
    )
    cert_path = cfg.certificate_path or DEFAULT_CERT
    key_path = cfg.key_path or DEFAULT_KEY
    kind = cfg.tls_le_kind or "auto"
    try:
        renew_certificate(
            creds,
            cfg.tls_le_domain,
            tls_kind=kind,
            cert_path=cert_path,
            key_path=key_path,
        )
    except ProvisioningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProvisioningError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    db.refresh(dbnode)
    try:
        status = refresh_node_tls(db, dbnode)
    except Exception:
        status = {"present": True, "trusted": True}
    bg.add_task(_sync_singbox_node, dbnode.id)
    return SingBoxTLSStatus(
        present=bool(status.get("present", True)),
        trusted=bool(dbnode.singbox.tls_trusted),
        issuer=dbnode.singbox.tls_issuer,
        expires_at=status.get("expires_at"),
        tls_le_domain=dbnode.singbox.tls_le_domain,
        tls_le_kind=dbnode.singbox.tls_le_kind,
    )


@router.post("/node/{node_id}/singbox/tls/refresh", response_model=SingBoxTLSStatus)
def refresh_singbox_tls(
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    from app.singbox.tls import refresh_node_tls

    if dbnode.singbox is None:
        raise HTTPException(status_code=400, detail="Configure sing-box on this node first")
    status = refresh_node_tls(db, dbnode)
    cfg = dbnode.singbox
    return SingBoxTLSStatus(
        present=bool(status.get("present")),
        trusted=bool(cfg.tls_trusted),
        issuer=cfg.tls_issuer,
        expires_at=status.get("expires_at"),
        tls_le_domain=cfg.tls_le_domain,
        tls_le_kind=cfg.tls_le_kind,
    )


class WGStackConfig(BaseModel):
    plain_enabled: Optional[bool] = None
    awg_enabled: Optional[bool] = None
    # Parallel, untunneled plain-WG port that stays up even when this node
    # delegates its main WG port to the Xray tunnel. 0 disables/clears it.
    direct_listen_port: Optional[int] = Field(default=None, ge=0, lt=65536)
    # Client-facing dial address (host or host:port). Empty string clears to
    # auto (provision_host / node.address). Used in .conf / subscription Endpoint=.
    endpoint: Optional[str] = Field(default=None, max_length=256)
    awg_endpoint: Optional[str] = Field(default=None, max_length=256)


class AmneziaWGStatus(BaseModel):
    """Runtime + config state for AmneziaWG on a WireGuard node."""
    plain_enabled: bool
    awg_enabled: bool
    sg_wire_enabled: bool = False
    sg_wire_preset_rev: Optional[str] = None
    runtime_ready: bool
    node_connected: bool
    needs_agent_upgrade: bool


@router.get("/node/{node_id}/amneziawg/status", response_model=AmneziaWGStatus)
def get_node_amneziawg_status(
    dbnode=Depends(get_dbnode),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    from app.models.node import CoreKind
    from app.wireguard.capabilities import node_amnezia_available
    from app.wireguard.operations import _node_object
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

    if dbnode.core_kind != CoreKind.wireguard.value:
        raise HTTPException(status_code=400, detail="Node is not a WireGuard node")
    cfg = dbnode.wireguard
    awg_on = amneziawg_enabled(cfg)
    connected = _node_object(dbnode.id) is not None
    runtime_ready = connected and node_amnezia_available(dbnode) if awg_on else False
    return AmneziaWGStatus(
        plain_enabled=plain_wg_enabled(cfg),
        awg_enabled=awg_on,
        sg_wire_enabled=bool(getattr(cfg, "sg_wire_enabled", False)) if cfg else False,
        sg_wire_preset_rev=getattr(cfg, "sg_wire_preset_rev", None) if cfg else None,
        runtime_ready=runtime_ready,
        node_connected=connected,
        needs_agent_upgrade=awg_on and not runtime_ready,
    )


@router.put("/node/{node_id}/wireguard/stack", response_model=NodeResponse)
def set_node_wireguard_stack(
    body: WGStackConfig,
    bg: BackgroundTasks,
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    from app.models.node import CoreKind

    if dbnode.core_kind != CoreKind.wireguard.value:
        raise HTTPException(status_code=400, detail="Node is not a WireGuard node")
    try:
        stack_kwargs = dict(
            plain_enabled=body.plain_enabled,
            awg_enabled=body.awg_enabled,
            direct_listen_port=body.direct_listen_port,
        )
        # Distinguish omitted vs explicitly cleared ("" / null → auto).
        payload = body.model_dump(exclude_unset=True)
        if "endpoint" in payload:
            stack_kwargs["endpoint"] = payload["endpoint"]
            stack_kwargs["endpoint_set"] = True
        if "awg_endpoint" in payload:
            stack_kwargs["awg_endpoint"] = payload["awg_endpoint"]
            stack_kwargs["awg_endpoint_set"] = True
        crud.set_node_wg_stack(db, dbnode, **stack_kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(dbnode)
    bg.add_task(_activate_wireguard_node, dbnode.id)
    return dbnode


@router.put("/node/{node_id}/amneziawg", response_model=NodeResponse)
def set_node_amneziawg(
    body: AmneziaWGConfig,
    bg: BackgroundTasks,
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
    db.refresh(dbnode)
    bg.add_task(_activate_wireguard_node, dbnode.id)
    return dbnode


class XrayNativeWireGuardConfig(BaseModel):
    """Xray-core's native userspace WireGuard inbound, Finalmask-noise obfuscated.

    Reuses this node's existing WireGuard keypair; only Xray-core-based
    clients (not the stock WireGuard app) can dial it once noise is applied.
    """
    enabled: Optional[bool] = None
    listen_port: Optional[int] = Field(default=None, gt=0, lt=65536)
    mtu: Optional[int] = Field(default=None, gt=0)
    noise: Optional[dict] = None


@router.put("/node/{node_id}/wireguard/xray-native", response_model=NodeResponse)
def set_node_xray_native_wireguard(
    body: XrayNativeWireGuardConfig,
    bg: BackgroundTasks,
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Configure the Xray-native WireGuard+Finalmask-noise inbound (sudo only).

    Unlike ``/wireguard/stack``, this changes the node's Xray config (a new
    inbound), so it triggers a full Xray restart on the node rather than a
    plain WG peer sync.
    """
    from app.models.node import CoreKind

    if dbnode.core_kind != CoreKind.wireguard.value:
        raise HTTPException(status_code=400, detail="Node is not a WireGuard node")
    try:
        crud.set_node_xray_wireguard(
            db, dbnode,
            enabled=body.enabled,
            listen_port=body.listen_port,
            mtu=body.mtu,
            noise=body.noise,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(dbnode)
    # Sync peers + open UDP firewall + restart Xray so Finalmask inbound is live.
    bg.add_task(_activate_wireguard_node, dbnode.id, restart_xray=True)
    return dbnode


@router.put("/node/{node_id}/sigmaguard-wire", response_model=NodeResponse)
def set_node_sigmaguard_wire(
    body: SgWireConfig,
    bg: BackgroundTasks,
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Enable proprietary SigmaGuard Wire preset on a WireGuard node (sudo only)."""
    from app import feature_flags
    from app.models.node import CoreKind

    if not feature_flags.is_enabled("sigmaguard_wire"):
        raise HTTPException(status_code=404, detail="SigmaGuard Wire is disabled")
    if dbnode.core_kind != CoreKind.wireguard.value:
        raise HTTPException(status_code=400, detail="Node is not a WireGuard node")
    try:
        crud.set_node_sg_wire(db, dbnode, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(dbnode)
    bg.add_task(_activate_wireguard_node, dbnode.id)
    return dbnode


def _sync_wireguard_node(node_id: int) -> None:
    """Backward-compatible alias for stack syncs."""
    _activate_wireguard_node(node_id, restart_xray=False)


def _activate_wireguard_node(node_id: int, *, restart_xray: bool = False) -> None:
    """Apply WG peers, open listen ports on the node, optionally restart Xray.

    Port / firewall changes are automatic — operators should not run iptables
    by hand when enabling Finalmask or changing UDP listen ports.
    """
    try:
        from app.db import GetDB
        from app.wireguard.operations import open_node_listen_ports, sync_node
        from app.wireguard.xray_native import xray_native_wg_enabled

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if not dbnode:
                return
            sync_ok = sync_node(db, dbnode)
            if not sync_ok:
                logger.warning(
                    "WireGuard sync during activate did not apply on node %s",
                    node_id,
                )
            cfg = dbnode.wireguard
            need_xray = restart_xray or xray_native_wg_enabled(cfg)
            if need_xray:
                try:
                    xray.operations.restart_node(node_id)
                except Exception:
                    logger.exception(
                        "Xray restart during WireGuard activate failed on node %s",
                        node_id,
                    )
            # Firewall rules live on the host; refresh after sync/restart.
            open_node_listen_ports(dbnode)
    except Exception:
        logger.exception("WireGuard activate failed on node %s", node_id)

@router.get("/node/{node_id}/xray-config")
def get_node_xray_config(
    dbnode=Depends(get_scoped_node),
    _: Admin = Depends(require_permission("nodes:read")),
):
    """Preview the effective Xray config this node would receive."""
    from app.services.xray_node import build_node_xray_config

    cfg = build_node_xray_config(dbnode.id)
    return cfg if isinstance(cfg, dict) else cfg.to_dict()


@router.get("/node/{node_id}/xray-config/override")
def get_node_xray_config_override(
    dbnode=Depends(get_scoped_node),
    _: Admin = Depends(require_permission("nodes:read")),
):
    """Return the stored per-node config override fragment (JSON object)."""
    import commentjson

    raw = getattr(dbnode, "xray_config_override", None)
    if not raw:
        return {}
    try:
        data = commentjson.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@router.put("/node/{node_id}/xray-config/override")
def set_node_xray_config_override(
    payload: dict,
    bg: BackgroundTasks,
    dbnode=Depends(get_scoped_node),
    db: Session = Depends(get_db),
    _: Admin = Depends(require_permission("nodes:provision")),
):
    """Save a JSON merge-patch applied after master filter + tunnels."""
    import commentjson

    dbnode.xray_config_override = commentjson.dumps(payload) if payload else None
    db.commit()
    bg.add_task(xray.operations.restart_node, dbnode.id)
    return {"saved": True}


@router.put("/node/{node_id}/warp", response_model=NodeResponse)
def set_node_warp(
    body: NodeWarpSettings,
    bg: BackgroundTasks,
    dbnode=Depends(get_scoped_node),
    db: Session = Depends(get_db),
    _: Admin = Depends(require_permission("nodes:provision")),
):
    """Enable/disable Cloudflare WARP as this node's default Xray exit.

    Requires a registered WARP account (Outbounds → WARP) for the chosen tag.
    """
    from app.utils import warp as warp_util

    tag = (body.tag or "warp").strip() or "warp"
    if body.enabled:
        account = warp_util.get_warp(tag)
        if not account or not account.get("outbound"):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No WARP account for tag '{tag}'. "
                    "Register one under Core → Outbounds → WARP first."
                ),
            )
    dbnode.warp_enabled = bool(body.enabled)
    dbnode.warp_tag = tag
    db.commit()
    db.refresh(dbnode)

    def _apply_warp_runtime(node_id: int) -> None:
        from app.db import GetDB, crud
        from app.services.panel_warp_egress import sync_panel_warp_egress
        from app.services.warp_node_sync import sync_node_warp_tproxy

        xray.operations.restart_node(node_id)
        with GetDB() as db:
            node = crud.get_node_by_id(db, node_id)
            if node is not None:
                sync_node_warp_tproxy(node)
            sync_panel_warp_egress(db)

    if dbnode.status != NodeStatus.disabled:
        bg.add_task(_apply_warp_runtime, dbnode.id)
    logger.info(
        'Node "%s" WARP %s (tag=%s)',
        dbnode.name,
        "enabled" if dbnode.warp_enabled else "disabled",
        dbnode.warp_tag or "warp",
    )
    return NodeResponse.model_validate(dbnode)


@router.post("/node/{node_id}/reconnect")
def reconnect_node(
    bg: BackgroundTasks,
    dbnode=Depends(get_scoped_node),
    _: Admin = Depends(require_permission("nodes:provision")),
):
    """Trigger a reconnection for a node in the caller's workspace."""
    bg.add_task(xray.operations.connect_node, node_id=dbnode.id)
    return {"detail": "Reconnection task scheduled"}


@router.post("/node/{node_id}/repin")
def repin_node_cert(
    bg: BackgroundTasks,
    dbnode=Depends(get_scoped_node),
    db: Session = Depends(get_db),
    _: Admin = Depends(require_permission("nodes:provision")),
):
    """Clear the pinned TLS cert so the next connection re-captures it (TOFU).

    Use after legitimately reissuing a node's certificate. There is no automatic
    rotation — call this endpoint when you intend to trust a new cert fingerprint.
    Until reconnect completes the pin stays cleared.
    """
    previous_pin = dbnode.server_cert_sha256
    dbnode.server_cert_sha256 = None
    db.commit()
    db.refresh(dbnode)
    try:
        live = xray.nodes[dbnode.id]
        live.pinned_cert_sha256 = None
        live.observed_cert_sha256 = None
    except KeyError:
        pass
    bg.add_task(xray.operations.connect_node, node_id=dbnode.id)
    logger.info(
        'Node "%s" cert pin cleared%s; reconnect scheduled',
        dbnode.name,
        f" (was {previous_pin[:16]}…)" if previous_pin else "",
    )
    return {
        "detail": "Cert pin cleared; reconnection scheduled",
        "node_id": dbnode.id,
        "had_pin": bool(previous_pin),
    }


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


class TopologyNode(BaseModel):
    id: int
    name: str
    address: str
    status: str
    role: Optional[str] = None
    region: Optional[str] = None
    core_kind: Optional[str] = None


class TopologyEdge(BaseModel):
    id: int
    name: str
    source: str
    target: str
    transport: str
    enabled: bool


class TopologyResponse(BaseModel):
    nodes: List[TopologyNode]
    edges: List[TopologyEdge]


@router.get("/nodes/topology", response_model=TopologyResponse)
def nodes_topology(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Visual topology: nodes as vertices, tunnels as directed edges."""
    from app.db.models import Node as DBNode, Tunnel

    query = db.query(DBNode)
    if not admin.is_sudo:
        dbadmin = crud.get_admin(db, admin.username)
        query = query.filter(DBNode.tenant_id == dbadmin.tenant_id)
    nodes = [
        TopologyNode(
            id=n.id,
            name=n.name,
            address=n.address,
            status=n.status.value if hasattr(n.status, "value") else str(n.status),
            role=getattr(n, "role", None),
            region=n.region,
            core_kind=getattr(n, "core_kind", None),
        )
        for n in query.all()
    ]
    edges: List[TopologyEdge] = []
    for t in db.query(Tunnel).all():
        relay = f"node:{t.relay_node_id}" if t.relay_node_id is not None else "panel"
        exit_end = f"node:{t.exit_node_id}" if t.exit_node_id is not None else "panel"
        if t.intermediate_node_id is not None:
            transit = f"node:{t.intermediate_node_id}"
            edges.append(
                TopologyEdge(
                    id=t.id,
                    name=f"{t.name} (hop 1)",
                    source=relay,
                    target=transit,
                    transport=t.transport,
                    enabled=bool(t.enabled),
                )
            )
            edges.append(
                TopologyEdge(
                    id=t.id * 10000 + 1,
                    name=f"{t.name} (hop 2)",
                    source=transit,
                    target=exit_end,
                    transport=t.transport,
                    enabled=bool(t.enabled),
                )
            )
        else:
            edges.append(
                TopologyEdge(
                    id=t.id,
                    name=t.name,
                    source=relay,
                    target=exit_end,
                    transport=t.transport,
                    enabled=bool(t.enabled),
                )
            )
    return TopologyResponse(nodes=nodes, edges=edges)
