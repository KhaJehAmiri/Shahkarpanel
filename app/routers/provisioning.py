"""Add a node over SSH by IP + password (phase 6).

A reseller pastes their server's IP and SSH credentials; the panel installs the
node agent and the agent self-registers (tagged to the reseller's tenant). When
SSH isn't available the endpoint returns the one-line install command to run
manually, so the feature degrades gracefully.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import feature_flags, logger
from app import provisioning, tenant as tenant_svc
from app.db import Session, get_db
from app.models.admin import Admin
from app.rbac import require_permission
from app.utils import responses
from config import (
    NODE_AGENT_IMAGE,
    NODE_BOOTSTRAP_TOKEN,
    NODE_DEFAULT_API_PORT,
    NODE_DEFAULT_PORT,
    NODE_PROVISION_SSH_TIMEOUT,
    PANEL_PUBLIC_ADDRESS,
    UVICORN_HOST,
    UVICORN_PORT,
)

router = APIRouter(
    tags=["Node provisioning"],
    prefix="/api/nodes",
    responses={401: responses._401, 403: responses._403},
)


def _require_enabled():
    if not feature_flags.is_enabled("node_provisioning"):
        raise HTTPException(status_code=404, detail="Node provisioning is disabled")


def _panel_address() -> str:
    return PANEL_PUBLIC_ADDRESS or f"{UVICORN_HOST}:{UVICORN_PORT}"


class ProvisionRequest(BaseModel):
    name: str
    host: str
    ssh_port: int = 22
    username: str = "root"
    password: Optional[str] = None
    private_key: Optional[str] = None
    role: str = "direct"
    run: bool = True   # when False, only return the install command


class ProvisionResponse(BaseModel):
    status: str               # "provisioned" | "manual"
    node_role: str
    install_command: str
    detail: Optional[str] = None
    output: Optional[str] = None


@router.get("/install-command", response_model=ProvisionResponse)
def install_command(
    name: str,
    role: str = "direct",
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("nodes:provision")),
):
    """Return the one-line command to provision a fresh server manually."""
    _require_enabled()
    if not NODE_BOOTSTRAP_TOKEN:
        raise HTTPException(
            status_code=400,
            detail="NODE_BOOTSTRAP_TOKEN is not set; provisioning is unavailable.",
        )
    tenant_id = tenant_svc.admin_tenant_id(db, admin)
    try:
        cmd = provisioning.build_install_command(
            _panel_address(), NODE_BOOTSTRAP_TOKEN, name,
            tenant_id=tenant_id, role=role, image=NODE_AGENT_IMAGE,
            node_port=NODE_DEFAULT_PORT, node_api_port=NODE_DEFAULT_API_PORT,
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
    """Provision a node on the reseller's own server via SSH.

    The agent self-registers via /api/node/bootstrap; this endpoint kicks off the
    install. If paramiko isn't installed (or SSH fails) we return the install
    command for manual use instead of failing hard.
    """
    _require_enabled()
    if not NODE_BOOTSTRAP_TOKEN:
        raise HTTPException(
            status_code=400,
            detail="NODE_BOOTSTRAP_TOKEN is not set; provisioning is unavailable.",
        )
    if body.role not in ("direct", "relay", "exit"):
        raise HTTPException(status_code=422, detail="invalid role")
    if not body.password and not body.private_key:
        raise HTTPException(status_code=422, detail="password or private_key is required")

    tenant_id = tenant_svc.admin_tenant_id(db, admin)
    try:
        cmd = provisioning.build_install_command(
            _panel_address(), NODE_BOOTSTRAP_TOKEN, body.name,
            tenant_id=tenant_id, role=body.role, image=NODE_AGENT_IMAGE,
            node_port=NODE_DEFAULT_PORT, node_api_port=NODE_DEFAULT_API_PORT,
        )
    except provisioning.ProvisioningError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not body.run or not provisioning.ssh_available():
        detail = (
            "SSH client (paramiko) unavailable; run the command on your server."
            if body.run else "Returning install command only (run=false)."
        )
        return ProvisionResponse(status="manual", node_role=body.role,
                                 install_command=cmd, detail=detail)

    creds = provisioning.SSHCredentials(
        host=body.host, port=body.ssh_port, username=body.username,
        password=body.password, private_key=body.private_key,
    )
    try:
        out = provisioning.run_remote_command(creds, cmd, timeout=NODE_PROVISION_SSH_TIMEOUT)
    except provisioning.ProvisioningError as exc:
        logger.warning("Node provisioning over SSH failed for %s: %s", body.host, exc)
        return ProvisionResponse(
            status="manual", node_role=body.role, install_command=cmd,
            detail=f"SSH provisioning failed ({exc}). Run the command manually.",
        )

    return ProvisionResponse(
        status="provisioned", node_role=body.role, install_command=cmd,
        detail="Server provisioned; the node will self-register shortly.",
        output=out[-2000:] if out else None,
    )
