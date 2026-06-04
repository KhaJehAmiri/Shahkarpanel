"""System operations: deployment metadata, panel updates, Xray release list."""
from __future__ import annotations

import json
import time
from typing import List, Optional
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import xray
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.system import update_jobs
from app.utils import responses
from app.utils.panel_region import deployment_snapshot
from app.xray.node import XRayNode

router = APIRouter(
    tags=["System Operations"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)

_XRAY_RELEASES_CACHE: dict = {"at": 0.0, "tags": []}
_XRAY_CACHE_TTL = 3600


class DeploymentInfo(BaseModel):
    panel_region: str
    detected_by: str
    public_ip: Optional[str] = None
    git_sha: Optional[str] = None
    xray_local_version: Optional[str] = None


class UpdateCheckResponse(BaseModel):
    current_sha: Optional[str] = None
    remote_sha: Optional[str] = None
    commits_behind: int = 0
    changelog_md: str = ""
    breaking: bool = False


class UpdateApplyResponse(BaseModel):
    job_id: str


class UpdateJobResponse(BaseModel):
    id: str
    status: str
    log: List[str]
    finished: bool


class XrayReleaseInfo(BaseModel):
    tag: str
    name: Optional[str] = None
    published_at: Optional[str] = None


class NodeXrayVersionBody(BaseModel):
    version: str


class PanelVersionInfo(BaseModel):
    version: str
    product: str = "NexusPanel"


class XrayUpgradeBody(BaseModel):
    tag: str


class XrayUpgradeResult(BaseModel):
    version: str
    scope: str


@router.get("/system/version", response_model=PanelVersionInfo)
def get_panel_version():
    from app import __version__ as pv

    return PanelVersionInfo(version=pv)


@router.get("/system/deployment", response_model=DeploymentInfo)
def get_deployment(_: Admin = Depends(Admin.check_sudo_admin)):
    return DeploymentInfo(**deployment_snapshot())


@router.get("/system/updates/check", response_model=UpdateCheckResponse)
def check_panel_updates(_: Admin = Depends(Admin.check_sudo_admin)):
    return UpdateCheckResponse(**update_jobs.check_updates())


@router.post("/system/updates/apply", response_model=UpdateApplyResponse)
def apply_panel_updates(_: Admin = Depends(Admin.check_sudo_admin)):
    job_id = update_jobs.start_apply_job()
    return UpdateApplyResponse(job_id=job_id)


@router.get("/system/updates/jobs/{job_id}", response_model=UpdateJobResponse)
def get_update_job(job_id: str, _: Admin = Depends(Admin.check_sudo_admin)):
    job = update_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return UpdateJobResponse(
        id=job.id,
        status=job.status,
        log=job.log[-200:],
        finished=job.status in ("success", "failed"),
    )


@router.get("/xray/releases", response_model=List[XrayReleaseInfo])
def list_xray_releases(_: Admin = Depends(Admin.check_sudo_admin)):
    now = time.time()
    if now - _XRAY_RELEASES_CACHE["at"] < _XRAY_CACHE_TTL and _XRAY_RELEASES_CACHE["tags"]:
        return _XRAY_RELEASES_CACHE["tags"]
    try:
        with urlopen(
            "https://api.github.com/repos/XTLS/Xray-core/releases?per_page=30",
            timeout=15,
        ) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch releases: {exc}") from exc
    tags = [
        XrayReleaseInfo(
            tag=item.get("tag_name") or "",
            name=item.get("name"),
            published_at=item.get("published_at"),
        )
        for item in data
        if item.get("tag_name")
    ]
    _XRAY_RELEASES_CACHE["at"] = now
    _XRAY_RELEASES_CACHE["tags"] = tags
    return tags


@router.post("/system/xray/upgrade", response_model=XrayUpgradeResult)
def upgrade_panel_xray(
    body: XrayUpgradeBody,
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Download and install Xray on the panel host, then restart local core."""
    from app.utils import xray_upgrade as xu
    from app import xray

    try:
        version = xu.install_xray_release(body.tag)
        try:
            xray.core.restart(xray.config.include_db_users())
        except Exception:
            pass
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return XrayUpgradeResult(version=version, scope="panel")


@router.post("/nodes/{node_id}/xray/version", response_model=XrayUpgradeResult)
def set_node_xray_version(
    node_id: int,
    body: NodeXrayVersionBody,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Record target Xray version and refresh reported version from the node agent."""
    dbnode = crud.get_node_by_id(db, node_id)
    if not dbnode:
        raise HTTPException(status_code=404, detail="Node not found")
    version = body.version.strip()
    if not version:
        raise HTTPException(status_code=400, detail="version required")
    from app.models.node import NodeStatus
    from app.xray import operations as xray_ops
    from app.xray.node import XRayNode
    from app.xray.operations import get_tls

    live_version = version
    try:
        tls = get_tls()
        remote = XRayNode(
            address=dbnode.address,
            port=dbnode.port,
            api_port=dbnode.api_port,
            ssl_key=tls["key"],
            ssl_cert=tls["certificate"],
            usage_coefficient=dbnode.usage_coefficient or 1,
        )
        live_version = remote.upgrade_xray(version)
        try:
            xray_ops.restart_node(node_id)
        except Exception:
            pass
    except Exception as exc:
        crud.update_node_status(
            db, dbnode, dbnode.status or NodeStatus.connected, version=version,
            message=f"upgrade pending: {exc}",
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    crud.update_node_status(db, dbnode, dbnode.status or NodeStatus.connected, version=live_version)
    return XrayUpgradeResult(version=live_version, scope=f"node:{node_id}")
