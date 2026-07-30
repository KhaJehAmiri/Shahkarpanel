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
from app.system import agent_update_jobs, update_jobs
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


class AgentNodeInfo(BaseModel):
    id: int
    name: str
    host: str = ""
    eligible: bool = False
    reason: Optional[str] = None
    core_kind: Optional[str] = None
    region: Optional[str] = None
    status: Optional[str] = None


class AgentUpdateCheckResponse(BaseModel):
    package_url: str = ""
    package_reachable: bool = False
    package_etag: Optional[str] = None
    package_last_modified: Optional[str] = None
    package_error: Optional[str] = None
    mirror_url: Optional[str] = None
    mirror_reachable: bool = False
    agent_image: str = "shahkar/node:latest"
    nodes_total: int = 0
    nodes_eligible: int = 0
    nodes_skipped: int = 0
    update_available: bool = False
    nodes: List[AgentNodeInfo] = []
    ssh_available: bool = False
    checked_at: int = 0


class AgentNodeJobInfo(BaseModel):
    node_id: int
    node_name: str
    host: str = ""
    status: str
    message: Optional[str] = None
    error: Optional[str] = None


class AgentUpdateJobResponse(BaseModel):
    id: str
    status: str
    finished: bool
    message: Optional[str] = None
    error_message: Optional[str] = None
    nodes: List[AgentNodeJobInfo] = []


class XrayReleaseInfo(BaseModel):
    tag: str
    name: Optional[str] = None
    published_at: Optional[str] = None


class NodeXrayVersionBody(BaseModel):
    version: str


class PanelVersionInfo(BaseModel):
    version: str
    product: str = "Shahkar"


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
def check_panel_updates(force: bool = False, _: Admin = Depends(Admin.check_sudo_admin)):
    return UpdateCheckResponse(**update_jobs.check_updates(force=force))


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


@router.get("/system/agent-updates/check", response_model=AgentUpdateCheckResponse)
def check_agent_updates(force: bool = False, _: Admin = Depends(Admin.check_sudo_admin)):
    return AgentUpdateCheckResponse(**agent_update_jobs.check_agent_updates(force=force))


@router.post("/system/agent-updates/apply", response_model=UpdateApplyResponse)
def apply_agent_updates(_: Admin = Depends(Admin.check_sudo_admin)):
    try:
        job_id = agent_update_jobs.start_fleet_apply()
    except agent_update_jobs.AgentUpdateInProgress as exc:
        raise HTTPException(
            status_code=409, detail="An agent update is already in progress"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UpdateApplyResponse(job_id=job_id)


@router.post("/system/agent-updates/apply/{node_id}", response_model=UpdateApplyResponse)
def apply_agent_update_node(node_id: int, _: Admin = Depends(Admin.check_sudo_admin)):
    try:
        job_id = agent_update_jobs.start_node_apply(node_id)
    except agent_update_jobs.AgentUpdateInProgress as exc:
        raise HTTPException(
            status_code=409, detail="An agent update is already in progress"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UpdateApplyResponse(job_id=job_id)


@router.get("/system/agent-updates/jobs/{job_id}", response_model=AgentUpdateJobResponse)
def get_agent_update_job(job_id: str, _: Admin = Depends(Admin.check_sudo_admin)):
    job = agent_update_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return AgentUpdateJobResponse(**agent_update_jobs.job_to_api(job))


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
    """Install the requested Xray release on the node agent and refresh status."""
    dbnode = crud.get_node_by_id(db, node_id)
    if not dbnode:
        raise HTTPException(status_code=404, detail="Node not found")
    version = body.version.strip()
    if not version:
        raise HTTPException(status_code=400, detail="version required")
    from app.models.node import CoreKind, NodeStatus
    from app.utils.xray_releases import normalize_xray_version_label
    from app.xray import operations as xray_ops
    from app.xray.node import XRayNode
    from app.xray.operations import get_tls

    live_version = version
    is_wg_node = (dbnode.core_kind or CoreKind.xray.value) == CoreKind.wireguard.value
    last_exc: Exception | None = None
    try:
        tls = get_tls()
        # Prefer the already-connected panel session when present — it keeps
        # the RPyC/REST channel warm and inherits any control-tunnel dial.
        from app import xray as xray_pkg

        remote = xray_pkg.nodes.get(node_id)
        if remote is None or not getattr(remote, "connected", False):
            remote = XRayNode(
                address=dbnode.address,
                port=dbnode.port,
                api_port=dbnode.api_port,
                ssl_key=tls["key"],
                ssl_cert=tls["certificate"],
                usage_coefficient=dbnode.usage_coefficient or 1,
            )
        for attempt in range(3):
            try:
                live_version = remote.upgrade_xray(version)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                if attempt >= 2 or not (
                    "stream has been closed" in msg
                    or "eof" in msg
                    or "result expired" in msg
                    or "timed out" in msg
                    or "timeout" in msg
                ):
                    break
                # Same Iran↔abroad mitigation used for large config pushes.
                forced = xray_ops._force_control_tunnel_session(dbnode, remote)
                if forced is not None:
                    remote = forced
                    continue
                try:
                    remote.connect()
                except Exception:
                    remote = XRayNode(
                        address=dbnode.address,
                        port=dbnode.port,
                        api_port=dbnode.api_port,
                        ssl_key=tls["key"],
                        ssl_cert=tls["certificate"],
                        usage_coefficient=dbnode.usage_coefficient or 1,
                    )
        if last_exc is not None:
            raise last_exc
        try:
            if is_wg_node:
                xray_ops.restart_node(node_id)
            else:
                xray_ops.restart_node(node_id, xray_pkg.config.include_db_users())
        except Exception:
            pass
    except Exception as exc:
        crud.update_node_status(
            db, dbnode, dbnode.status or NodeStatus.connected, version=version,
            message=f"upgrade pending: {exc}"[:512],
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    short = normalize_xray_version_label(live_version) or version
    crud.update_node_status(
        db, dbnode, dbnode.status or NodeStatus.connected, version=short, message=None,
    )
    return XrayUpgradeResult(version=short, scope=f"node:{node_id}")
