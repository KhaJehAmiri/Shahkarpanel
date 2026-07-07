"""Add a node over SSH by IP + password (phase 6).

Creates a placeholder node immediately, runs SSH install in the background, and
exposes job progress for the dashboard progress bar.
"""
import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app import feature_flags, provisioning
from app.bootstrap_limit import enforce_bootstrap_rate_limit
from app.provisioning import jobs as provision_jobs
from app.provisioning.agent_bundle import build_agent_bundle
from app import tenant as tenant_svc
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.models.node import CoreKind, NodeCreate, NodeStatus
from app.rbac import require_permission
from app.utils import responses
from config import (
    NODE_AGENT_IMAGE,
    NODE_BOOTSTRAP_TOKEN,
    NODE_CONTROL_SECRET,
    NODE_DEFAULT_API_PORT,
    NODE_DEFAULT_PORT,
    NODE_PROVISION_EXEC_TIMEOUT,
    NODE_PROVISION_SSH_TIMEOUT,
)

router = APIRouter(
    tags=["Node provisioning"],
    prefix="/api/nodes",
    responses={401: responses._401, 403: responses._403},
)


def _require_enabled():
    if not feature_flags.is_enabled("node_provisioning"):
        raise HTTPException(status_code=404, detail="Node provisioning is disabled")


def _panel_url() -> str:
    try:
        return provisioning.resolve_panel_public_url()
    except provisioning.ProvisioningError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _client_cert_pem(db: Session) -> Optional[str]:
    """The panel's own TLS certificate, pushed to new nodes as SSL_CLIENT_CERT_FILE
    so the node's RPyC/REST control channel requires real mutual TLS (H11)."""
    tls = crud.get_tls_certificate(db)
    return tls.certificate if tls else None


class ProvisionRequest(BaseModel):
    name: str
    host: str
    ssh_port: int = 22
    username: str = "root"
    password: Optional[str] = None
    private_key: Optional[str] = None
    role: str = "direct"
    core_kind: str = "xray"
    region: Optional[str] = None
    run: bool = True
    refresh_agent: bool = False
    enable_plain_wg: bool = True
    enable_awg_wg: bool = False
    # sing-box stack (xray nodes)
    enable_hysteria2: bool = True
    enable_tuic: bool = False
    enable_anytls: bool = False
    tls_mode: str = "self_signed"  # self_signed | letsencrypt | none
    tls_self_signed: bool = True
    le_target: Optional[str] = None
    le_email: Optional[str] = None
    le_kind: str = "auto"
    # tunnel (xray nodes, requires tunneling flag)
    create_tunnel: bool = False
    tunnel_port: int = 443
    enable_plain_wg_on_xray: bool = False
    enable_awg_on_xray: bool = False


class ProvisionResponse(BaseModel):
    status: str
    node_role: str
    job_id: Optional[str] = None
    node_id: Optional[int] = None
    install_command: str = ""
    detail: Optional[str] = None


class ProvisionJobResponse(BaseModel):
    job_id: str
    node_id: int
    node_name: str
    status: str
    progress: int
    step: str
    message: Optional[str] = None
    error: Optional[str] = None


@router.get("/agent-bundle")
def agent_bundle(request: Request, token: str):
    """Gzip tarball of ``node/`` for remote ``docker build`` during SSH provision."""
    enforce_bootstrap_rate_limit(request)
    if not NODE_BOOTSTRAP_TOKEN or not hmac.compare_digest(token, NODE_BOOTSTRAP_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid bootstrap token")
    try:
        payload = build_agent_bundle()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(
        content=payload,
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="nexuspanel-node-agent.tar.gz"'},
    )


@router.get("/provision/jobs/{job_id}", response_model=ProvisionJobResponse)
def get_provision_job(
    job_id: str,
    _: Admin = Depends(require_permission("nodes:provision")),
):
    job = provision_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Provision job not found")
    return ProvisionJobResponse(**provision_jobs.job_to_api(job))


@router.get("/install-command", response_model=ProvisionResponse)
def install_command(
    name: str,
    role: str = "direct",
    core_kind: str = "xray",
    region: Optional[str] = None,
    rebuild: bool = False,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("nodes:provision")),
):
    _require_enabled()
    if not NODE_BOOTSTRAP_TOKEN:
        raise HTTPException(status_code=400, detail="NODE_BOOTSTRAP_TOKEN is not set.")
    if core_kind not in ("xray", "wireguard"):
        raise HTTPException(status_code=422, detail="invalid core_kind")
    tenant_id = tenant_svc.admin_tenant_id(db, admin)
    panel_url = _panel_url()
    try:
        cmd = provisioning.build_install_command(
            panel_url, NODE_BOOTSTRAP_TOKEN, name,
            tenant_id=tenant_id, role=role, core_kind=core_kind, region=region,
            image=NODE_AGENT_IMAGE,
            node_port=NODE_DEFAULT_PORT, node_api_port=NODE_DEFAULT_API_PORT,
            control_secret=NODE_CONTROL_SECRET or None,
            force_image_rebuild=rebuild,
            client_cert_pem=_client_cert_pem(db),
        )
    except provisioning.ProvisioningError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ProvisionResponse(status="manual", node_role=role, install_command=cmd,
                             detail="Run this on your server as root.")


@router.post("/provision", response_model=ProvisionResponse)
def provision_node(
    body: ProvisionRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("nodes:provision")),
):
    """Queue SSH provisioning: placeholder node appears instantly; install runs in background."""
    _require_enabled()
    if not NODE_BOOTSTRAP_TOKEN:
        raise HTTPException(status_code=400, detail="NODE_BOOTSTRAP_TOKEN is not set.")
    if body.role not in ("direct", "relay", "transit", "exit"):
        raise HTTPException(status_code=422, detail="invalid role")
    if body.core_kind not in ("xray", "wireguard"):
        raise HTTPException(status_code=422, detail="invalid core_kind")
    if body.core_kind == "wireguard" and not body.enable_plain_wg and not body.enable_awg_wg:
        raise HTTPException(status_code=422, detail="enable at least one of plain WireGuard or AmneziaWG")
    if not body.password and not body.private_key:
        raise HTTPException(status_code=422, detail="password or private_key is required")

    from app.tenant.reseller_ops import assert_can_add_node, db_admin

    if body.run:
        assert_can_add_node(db, admin)

    if not body.run:
        tenant_id = tenant_svc.admin_tenant_id(db, admin)
        panel_url = _panel_url()
        cmd = provisioning.build_install_command(
            panel_url, NODE_BOOTSTRAP_TOKEN, body.name,
            tenant_id=tenant_id, role=body.role, core_kind=body.core_kind,
            region=body.region, image=NODE_AGENT_IMAGE,
            node_port=NODE_DEFAULT_PORT, node_api_port=NODE_DEFAULT_API_PORT,
            control_secret=NODE_CONTROL_SECRET or None,
            client_cert_pem=_client_cert_pem(db),
        )
        return ProvisionResponse(
            status="manual", node_role=body.role, install_command=cmd,
            detail="Returning install command only (run=false).",
        )

    if not provisioning.ssh_available():
        raise HTTPException(
            status_code=503,
            detail="SSH provisioning is unavailable (paramiko not installed).",
        )

    tenant_id = tenant_svc.admin_tenant_id(db, admin)
    panel_url = _panel_url()
    try:
        cmd = provisioning.build_install_command(
            panel_url, NODE_BOOTSTRAP_TOKEN, body.name,
            tenant_id=tenant_id, role=body.role, core_kind=body.core_kind,
            region=body.region, image=NODE_AGENT_IMAGE,
            node_port=NODE_DEFAULT_PORT, node_api_port=NODE_DEFAULT_API_PORT,
            control_secret=NODE_CONTROL_SECRET or None,
            force_image_rebuild=body.refresh_agent,
            client_cert_pem=_client_cert_pem(db),
        )
    except provisioning.ProvisioningError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    from app.db.models import Node as DBNode

    name = body.name.strip()
    existing = db.query(DBNode).filter(DBNode.name == name).first()
    if existing and (
        existing.provision_status in ("failed", "provisioning")
        or body.refresh_agent
    ):
        dbnode = existing
        dbnode.address = body.host.strip()
        dbnode.port = NODE_DEFAULT_PORT
        dbnode.api_port = NODE_DEFAULT_API_PORT
        dbnode.region = body.region
        dbnode.core_kind = CoreKind(body.core_kind).value
        dbnode.role = body.role
        dbnode.tenant_id = tenant_id
        owner = db_admin(db, admin)
        if owner:
            dbnode.owner_admin_id = owner.id
        dbnode.provision_status = "provisioning"
        dbnode.provision_host = body.host.strip()
        dbnode.provision_message = "queued"
        dbnode.message = None
        dbnode.status = NodeStatus.connecting
        db.commit()
        db.refresh(dbnode)
        if dbnode.core_kind == CoreKind.wireguard.value:
            if dbnode.wireguard is None:
                crud.provision_wireguard_defaults(
                    db, dbnode,
                    plain_enabled=body.enable_plain_wg,
                    awg_enabled=body.enable_awg_wg,
                )
            else:
                crud.set_node_wg_stack(
                    db, dbnode,
                    plain_enabled=body.enable_plain_wg,
                    awg_enabled=body.enable_awg_wg,
                )
    else:
        try:
            dbnode = crud.create_node(
                db,
                NodeCreate(
                    name=name,
                    address=body.host.strip(),
                    port=NODE_DEFAULT_PORT,
                    api_port=NODE_DEFAULT_API_PORT,
                    region=body.region,
                    core_kind=CoreKind(body.core_kind),
                    add_as_new_host=False,
                ),
            )
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail=f'Node "{body.name}" already exists')

        dbnode.role = body.role
        dbnode.tenant_id = tenant_id
        owner = db_admin(db, admin)
        if owner:
            dbnode.owner_admin_id = owner.id
        dbnode.provision_status = "provisioning"
        dbnode.provision_host = body.host.strip()
        dbnode.provision_message = "queued"
        dbnode.status = NodeStatus.connecting
        db.commit()
        db.refresh(dbnode)
        if dbnode.core_kind == CoreKind.wireguard.value:
            if dbnode.wireguard is None:
                crud.provision_wireguard_defaults(
                    db, dbnode,
                    plain_enabled=body.enable_plain_wg,
                    awg_enabled=body.enable_awg_wg,
                )
            else:
                crud.set_node_wg_stack(
                    db, dbnode,
                    plain_enabled=body.enable_plain_wg,
                    awg_enabled=body.enable_awg_wg,
                )

    creds = provisioning.SSHCredentials(
        host=body.host.strip(), port=body.ssh_port, username=body.username,
        password=body.password, private_key=body.private_key,
    )
    from app.provisioning.post_install import ProvisionExtras

    tls_mode = (body.tls_mode or "self_signed").strip().lower()
    if tls_mode not in ("self_signed", "letsencrypt", "none"):
        tls_mode = "self_signed"
    extras = ProvisionExtras(
        enable_hysteria2=body.enable_hysteria2,
        enable_tuic=body.enable_tuic,
        enable_anytls=body.enable_anytls,
        tls_mode=tls_mode,
        le_target=(body.le_target or "").strip() or None,
        le_email=(body.le_email or "").strip() or None,
        le_kind=body.le_kind,
        create_tunnel=body.create_tunnel and feature_flags.is_enabled("tunneling"),
        tunnel_port=body.tunnel_port,
        region=body.region or dbnode.region,
        enable_plain_wg_on_xray=body.enable_plain_wg_on_xray,
        enable_awg_on_xray=body.enable_awg_on_xray,
        enable_awg_wg=body.enable_awg_wg,
    )
    job_id = provision_jobs.start_job(
        node_id=dbnode.id,
        node_name=dbnode.name,
        creds=creds,
        command=cmd,
        ssh_timeout=NODE_PROVISION_SSH_TIMEOUT,
        exec_timeout=NODE_PROVISION_EXEC_TIMEOUT,
        extras=extras,
    )

    return ProvisionResponse(
        status="started",
        job_id=job_id,
        node_id=dbnode.id,
        node_role=body.role,
        detail="Install started — track progress in the nodes list.",
    )
