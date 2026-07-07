"""System operations: deployment metadata, panel updates, Xray release list."""
from __future__ import annotations

import json
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app import logger, xray
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

class DeploymentInfo(BaseModel):
    panel_region: str
    detected_by: str
    public_ip: Optional[str] = None
    git_sha: Optional[str] = None
    xray_local_version: Optional[str] = None


class UpdateCheckResponse(BaseModel):
    current_version: str = "0.0.0"
    remote_version: str = "0.0.0"
    current_sha: Optional[str] = None
    remote_sha: Optional[str] = None
    commits_behind: int = 0
    update_available: bool = False
    check_source: str = "none"
    changelog_md: str = ""
    release_notes: str = ""
    release_notes_i18n: dict = {}
    breaking: bool = False


class UpdateStepInfo(BaseModel):
    id: str
    status: str
    detail: Optional[str] = None


class UpdateApplyResponse(BaseModel):
    job_id: str


class UpdateJobResponse(BaseModel):
    id: str
    status: str
    finished: bool
    error_message: Optional[str] = None
    steps: List[UpdateStepInfo] = []


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
    restart_warning: Optional[str] = None


@router.get("/system/version", response_model=PanelVersionInfo)
def get_panel_version(response: Response, _: Admin = Depends(Admin.check_sudo_admin)):
    from app import panel_version

    response.headers["Cache-Control"] = "no-store"
    return PanelVersionInfo(version=panel_version())


@router.get("/system/deployment", response_model=DeploymentInfo)
def get_deployment(_: Admin = Depends(Admin.check_sudo_admin)):
    return DeploymentInfo(**deployment_snapshot())


@router.get("/system/updates/check", response_model=UpdateCheckResponse)
def check_panel_updates(_: Admin = Depends(Admin.check_sudo_admin)):
    return UpdateCheckResponse(**update_jobs.check_updates())


@router.post("/system/updates/apply", response_model=UpdateApplyResponse)
def apply_panel_updates(_: Admin = Depends(Admin.check_sudo_admin)):
    try:
        job_id = update_jobs.start_apply_job()
    except update_jobs.UpdateInProgress as exc:
        raise HTTPException(status_code=409, detail="An update is already in progress") from exc
    return UpdateApplyResponse(job_id=job_id)


@router.get("/system/updates/jobs/{job_id}", response_model=UpdateJobResponse)
def get_update_job(job_id: str, _: Admin = Depends(Admin.check_sudo_admin)):
    job = update_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = update_jobs.job_to_api(job)
    return UpdateJobResponse(**payload)


@router.get("/xray/releases", response_model=List[XrayReleaseInfo])
def list_xray_releases(_: Admin = Depends(Admin.check_sudo_admin)):
    from app.utils.xray_releases import fetch_xray_releases

    try:
        data = fetch_xray_releases()
    except Exception as exc:
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
        version = xu.install_xray_release(body.tag, stop_running=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    restart_warning = None
    try:
        xray.core.version = xray.core.get_version()
        xray.core.restart(xray.config.include_db_users())
    except Exception as exc:
        # The new binary is installed; a failed restart is recoverable but must
        # not be hidden — surface it so the admin knows to restart manually.
        logger.error("Xray %s installed but core restart failed: %s", version, exc)
        restart_warning = str(exc)
    return XrayUpgradeResult(version=version, scope="panel", restart_warning=restart_warning)


@router.post("/system/xray/auto-upgrade")
def trigger_xray_auto_upgrade(_: Admin = Depends(Admin.check_sudo_admin)):
    """Upgrade panel + all Xray nodes to the newest GitHub release if outdated."""
    from app.services.xray_auto_upgrade import run_xray_auto_upgrade

    try:
        return run_xray_auto_upgrade(force=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class XrayAutoUpgradeSchedule(BaseModel):
    enabled: bool = True
    interval_seconds: int = 21600
    include_prerelease: bool = True


@router.get("/system/xray/auto-upgrade/schedule")
def get_xray_auto_upgrade_schedule(_: Admin = Depends(Admin.check_sudo_admin)):
    from app.utils.runtime_settings import xray_auto_upgrade_config

    return xray_auto_upgrade_config()


@router.put("/system/xray/auto-upgrade/schedule")
def set_xray_auto_upgrade_schedule(
    body: XrayAutoUpgradeSchedule,
    _: Admin = Depends(Admin.check_sudo_admin),
):
    from app.jobs.xray_auto_upgrade import reschedule_xray_auto_upgrade_job
    from app.utils.runtime_settings import set_value

    interval = max(3600, min(int(body.interval_seconds), 604800))
    set_value("xray_auto_upgrade_enabled", bool(body.enabled))
    set_value("xray_auto_upgrade_interval", interval)
    set_value("xray_auto_upgrade_include_prerelease", bool(body.include_prerelease))
    reschedule_xray_auto_upgrade_job()
    from app.utils.runtime_settings import xray_auto_upgrade_config

    return xray_auto_upgrade_config()


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
