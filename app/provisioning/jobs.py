"""Background SSH provision jobs with progress for the nodes UI."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional

from app import provisioning
from app.db import GetDB, crud
from app.models.node import NodeStatus
from app.provisioning.post_install import ProvisionExtras, run_post_provision

logger = logging.getLogger("nexus-provision")

JobStatus = Literal["pending", "running", "success", "failed"]
STEP_LABELS = ("queued", "ssh", "docker", "image", "agent", "register", "done")

_lock = threading.Lock()
_jobs: Dict[str, "ProvisionJob"] = {}
_by_node: Dict[int, str] = {}
_extras: Dict[str, ProvisionExtras] = {}


@dataclass
class ProvisionJob:
    id: str
    node_id: int
    node_name: str
    status: JobStatus = "pending"
    progress: int = 0
    step: str = "queued"
    message: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


def _set_node_provision(node_id: int, *, status: str, message: Optional[str] = None,
                        node_status: Optional[NodeStatus] = None) -> None:
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if not dbnode:
            return
        dbnode.provision_status = status
        dbnode.provision_message = message
        if node_status is not None:
            dbnode.status = node_status
            if node_status == NodeStatus.error and message:
                dbnode.message = message[:1024]
        db.commit()


def _tick_progress(job: ProvisionJob, stop: threading.Event) -> None:
    """Gentle time-based progress while the remote install script runs."""
    while not stop.wait(12):
        with _lock:
            if job.status != "running" or job.progress >= 88:
                return
            job.progress = min(88, job.progress + 4)
            if job.progress < 25:
                job.step = "docker"
            elif job.progress < 70:
                job.step = "image"
            else:
                job.step = "agent"


def _panel_finish_registration(node_id: int) -> bool:
    """Register the placeholder from the panel when remote bootstrap cannot reach us."""
    from app.models.node import CoreKind
    from app.xray import operations as xray_ops

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if not dbnode:
            return False
        if dbnode.provision_status == "registered":
            return True
        if dbnode.provision_status not in ("provisioning", "failed"):
            return False
        dbnode.address = (dbnode.provision_host or dbnode.address or "").strip()
        dbnode.provision_status = "registered"
        dbnode.provision_message = None
        dbnode.status = NodeStatus.connecting
        dbnode.message = None
        db.commit()
        if dbnode.core_kind == CoreKind.wireguard.value and dbnode.wireguard is None:
            crud.provision_wireguard_defaults(db, dbnode)
        db.refresh(dbnode)
        node_id = dbnode.id

    logger.info("Finished provisioning registration for node %s from panel", node_id)
    xray_ops.connect_node(node_id)
    return True


def _wait_registered(node_id: int, timeout: int = 180) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if not dbnode:
                return False
            if dbnode.provision_status == "registered":
                return True
            if dbnode.provision_status == "failed":
                return False
        time.sleep(3)
    return False


def _run_job(job_id: str, creds: provisioning.SSHCredentials, command: str,
             ssh_timeout: int, exec_timeout: int) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.progress = 8
        job.step = "ssh"
        job.message = "Connecting over SSH…"

    _set_node_provision(job.node_id, status="provisioning", message=job.message)

    stop = threading.Event()
    ticker = threading.Thread(target=_tick_progress, args=(job, stop), daemon=True)
    ticker.start()

    try:
        provisioning.run_remote_command(
            creds, command, timeout=ssh_timeout, exec_timeout=exec_timeout,
        )
        stop.set()
        with _lock:
            job.progress = 92
            job.step = "register"
            job.message = "Waiting for the agent to register…"
        _set_node_provision(job.node_id, status="provisioning", message=job.message)

        if not _wait_registered(job.node_id, timeout=25):
            logger.info(
                "Node %s agent is up but remote bootstrap did not register; using panel-side registration",
                job.node_id,
            )
            _panel_finish_registration(job.node_id)

        if not _wait_registered(job.node_id, timeout=45):
            raise provisioning.ProvisioningError(
                "Agent installed but registration did not complete. "
                "Check that the node agent is running (docker ps) and the panel can reach its API ports."
            )

        extras = _extras.get(job_id)
        if extras:
            with _lock:
                job.progress = 94
                job.step = "post"
                job.message = "Configuring sing-box, TLS, and tunnel…"
            _set_node_provision(job.node_id, status="provisioning", message=job.message)
            try:
                run_post_provision(job.node_id, creds, extras)
            except Exception as exc:
                logger.warning(
                    "Post-provision steps failed for node %s (agent is up): %s",
                    job.node_id,
                    exc,
                )

        with _lock:
            job.status = "success"
            job.progress = 100
            job.step = "done"
            job.message = None
            job.finished_at = time.time()
            _extras.pop(job_id, None)
        _set_node_provision(job.node_id, status="registered", message=None)
    except Exception as exc:
        stop.set()
        err = str(exc)
        logger.warning("Provision job %s failed for node %s: %s", job_id, job.node_id, err)
        with _lock:
            job.status = "failed"
            job.error = err
            job.message = err
            job.step = "failed"
            job.finished_at = time.time()
            _extras.pop(job_id, None)
        _set_node_provision(
            job.node_id,
            status="failed",
            message=err,
            node_status=NodeStatus.error,
        )
    finally:
        with _lock:
            _by_node.pop(job.node_id, None)


def start_job(
    *,
    node_id: int,
    node_name: str,
    creds: provisioning.SSHCredentials,
    command: str,
    ssh_timeout: int,
    exec_timeout: int,
    extras: Optional[ProvisionExtras] = None,
) -> str:
    job_id = uuid.uuid4().hex
    job = ProvisionJob(id=job_id, node_id=node_id, node_name=node_name)
    with _lock:
        _jobs[job_id] = job
        _by_node[node_id] = job_id
        if extras is not None:
            _extras[job_id] = extras
    threading.Thread(
        target=_run_job,
        args=(job_id, creds, command, ssh_timeout, exec_timeout),
        daemon=True,
    ).start()
    return job_id


def get_job(job_id: str) -> Optional[ProvisionJob]:
    with _lock:
        return _jobs.get(job_id)


def progress_for_node(node_id: int) -> Optional[ProvisionJob]:
    with _lock:
        jid = _by_node.get(node_id)
        return _jobs.get(jid) if jid else None


def complete_for_node(node_id: int) -> None:
    """Called when bootstrap finishes for a placeholder node."""
    with _lock:
        jid = _by_node.get(node_id)
        if not jid:
            return
        job = _jobs.get(jid)
        if not job or job.status != "running":
            return
        job.status = "success"
        job.progress = 100
        job.step = "done"
        job.message = None
        job.finished_at = time.time()
        _by_node.pop(node_id, None)


def job_to_api(job: ProvisionJob) -> dict:
    return {
        "job_id": job.id,
        "node_id": job.node_id,
        "node_name": job.node_name,
        "status": job.status,
        "progress": job.progress,
        "step": job.step,
        "message": job.message,
        "error": job.error,
    }
