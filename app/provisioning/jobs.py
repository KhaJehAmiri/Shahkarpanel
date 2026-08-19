"""Background SSH provision jobs with progress for the nodes UI."""
from __future__ import annotations

import json
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

logger = logging.getLogger("shahkar-provision")

JobStatus = Literal["pending", "running", "success", "failed"]
STEP_LABELS = ("queued", "ssh", "docker", "image", "agent", "register", "done")
_PROVISION_MSG_MAX = 1000

_lock = threading.Lock()
_jobs: Dict[str, "ProvisionJob"] = {}
_by_node: Dict[int, str] = {}
_extras: Dict[str, ProvisionExtras] = {}
_REDIS_TTL = 7200
_REDIS_JOB = "shahkar:provision:job:{}"
_REDIS_NODE = "shahkar:provision:node:{}"


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


def _redis():
    try:
        from config import REDIS_URL

        if not REDIS_URL:
            return None
        import redis

        return redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.5,
        )
    except Exception:
        return None


def _job_payload(job: "ProvisionJob") -> dict:
    return {
        "id": job.id,
        "node_id": job.node_id,
        "node_name": job.node_name,
        "status": job.status,
        "progress": int(job.progress or 0),
        "step": job.step,
        "message": job.message,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


def _job_from_payload(data: dict) -> "ProvisionJob":
    return ProvisionJob(
        id=str(data.get("id") or ""),
        node_id=int(data.get("node_id") or 0),
        node_name=str(data.get("node_name") or ""),
        status=data.get("status") or "pending",
        progress=int(data.get("progress") or 0),
        step=str(data.get("step") or "queued"),
        message=data.get("message"),
        error=data.get("error"),
        created_at=float(data.get("created_at") or time.time()),
        finished_at=data.get("finished_at"),
    )


def _publish_job(job: "ProvisionJob") -> None:
    """So GET /nodes on another uvicorn worker can show the progress bar."""
    client = _redis()
    if client is None:
        return
    try:
        payload = json.dumps(_job_payload(job))
        pipe = client.pipeline()
        pipe.set(_REDIS_JOB.format(job.id), payload, ex=_REDIS_TTL)
        pipe.set(_REDIS_NODE.format(int(job.node_id)), job.id, ex=_REDIS_TTL)
        pipe.execute()
    except Exception:
        logger.debug("provision job redis publish failed", exc_info=True)
    finally:
        try:
            client.close()
        except Exception:
            pass


def _load_job_for_node(node_id: int) -> Optional["ProvisionJob"]:
    client = _redis()
    if client is None:
        return None
    try:
        jid = client.get(_REDIS_NODE.format(int(node_id)))
        if not jid:
            return None
        raw = client.get(_REDIS_JOB.format(jid))
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return _job_from_payload(data)
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def _clip_provision_message(message: Optional[str]) -> Optional[str]:
    if message is None:
        return None
    msg = message.strip()
    if len(msg) <= _PROVISION_MSG_MAX:
        return msg
    return msg[: _PROVISION_MSG_MAX - 3] + "..."


def _set_node_provision(node_id: int, *, status: str, message: Optional[str] = None,
                        node_status: Optional[NodeStatus] = None) -> None:
    clipped = _clip_provision_message(message)
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if not dbnode:
            return
        dbnode.provision_status = status
        dbnode.provision_message = clipped
        if node_status is not None:
            dbnode.status = node_status
            if node_status == NodeStatus.error and clipped:
                dbnode.message = clipped
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
        _publish_job(job)


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
    # Prefer an SSH control tunnel right after provision — some routes drop
    # direct RPyC application data even when TLS handshakes succeed.
    try:
        from app.control_tunnel import ensure_node_tunnel, has_ssh_for_host

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            host = (
                (getattr(dbnode, "provision_host", None) or dbnode.address or "").strip()
                if dbnode
                else ""
            )
            port = dbnode.port if dbnode else 62050
            api_port = dbnode.api_port if dbnode else 62051
        if host and has_ssh_for_host(host):
            ensure_node_tunnel(
                node_id, host, remote_port=port, remote_api_port=api_port
            )
    except Exception as exc:
        logger.warning(
            "Could not pre-start control tunnel for node %s: %s", node_id, exc
        )
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


def _run_job(
    job_id: str,
    creds: provisioning.SSHCredentials,
    command: str,
    ssh_timeout: int,
    exec_timeout: int,
    force_image: bool = False,
    use_iran_mirror: bool = False,
) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.progress = 8
        job.step = "ssh"
        job.message = "Connecting over SSH…"
    _publish_job(job)

    _set_node_provision(job.node_id, status="provisioning", message=job.message)

    stop = threading.Event()
    ticker = threading.Thread(target=_tick_progress, args=(job, stop), daemon=True)
    ticker.start()

    try:
        with _lock:
            job.progress = 12
            job.step = "docker"
            job.message = "Installing Docker on the node…"
        _publish_job(job)
        _set_node_provision(job.node_id, status="provisioning", message=job.message)
        provisioning.run_remote_command(
            creds,
            "set -e; " + provisioning.install_docker_shell(),
            timeout=ssh_timeout,
            exec_timeout=min(exec_timeout, 600),
        )

        # Authorize the panel's own control-tunnel key now, while we still
        # have a working one-time credential. Every maintenance connection
        # after this job finishes (control tunnel, restarts, TLS renewals)
        # uses that persistent key instead of this password/key — no manual
        # setup_node_ssh_access.py run, ever, for any node added this way.
        try:
            provisioning.install_control_pubkey(creds, timeout=ssh_timeout)
        except Exception:
            logger.warning(
                "Could not pre-authorize control-tunnel key for node %s (will retry via password fallback)",
                job.node_id,
            )

        with _lock:
            job.progress = 28
            job.step = "image"
            job.message = (
                "Refreshing agent image (force re-download)…"
                if force_image
                else "Node will download agent image from GitHub…"
            )
        _publish_job(job)
        _set_node_provision(job.node_id, status="provisioning", message=job.message)

        # Heavy image comes from GitHub (then Iran mirror). When force_image is
        # set and the remote fetch fails, fall back to SSH upload from the panel.
        _ = use_iran_mirror  # mirror URL is already baked into ``command``
        logger.info(
            "Agent image for node %s via GitHub package URL (force=%s)",
            job.node_id,
            force_image,
        )

        with _lock:
            job.progress = 55
            job.step = "agent"
            job.message = "Starting node agent…"
        _publish_job(job)
        _set_node_provision(job.node_id, status="provisioning", message=job.message)
        try:
            provisioning.run_remote_command(
                creds, command, timeout=ssh_timeout, exec_timeout=exec_timeout,
            )
        except provisioning.ProvisioningError as exc:
            if not (
                force_image or provisioning.is_agent_image_fetch_error(exc)
            ):
                raise
            logger.warning(
                "Remote agent image fetch failed for node %s (%s); uploading via SSH",
                job.node_id,
                exc,
            )
            with _lock:
                job.step = "image"
                job.message = "GitHub/mirror fetch failed — uploading image via SSH…"
            _publish_job(job)
            _set_node_provision(job.node_id, status="provisioning", message=job.message)
            provisioning.push_agent_image_via_ssh(
                creds,
                force=True,
                timeout=ssh_timeout,
                transfer_timeout=min(exec_timeout, 1800),
            )
            with _lock:
                job.step = "agent"
                job.message = "Restarting node agent with uploaded image…"
            _publish_job(job)
            _set_node_provision(job.node_id, status="provisioning", message=job.message)
            soft = provisioning.soft_restart_agent_command(command)
            provisioning.run_remote_command(
                creds, soft, timeout=ssh_timeout, exec_timeout=exec_timeout,
            )
        stop.set()
        with _lock:
            job.progress = 92
            job.step = "register"
            job.message = "Waiting for the agent to register…"
        _publish_job(job)
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
            _publish_job(job)
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
        _publish_job(job)
        _set_node_provision(job.node_id, status="registered", message=None)
        try:
            from app.control_tunnel import ensure_node_tunnel
            from app.xray import operations as xray_ops

            with GetDB() as db:
                dbnode = crud.get_node_by_id(db, job.node_id)
                remote_port = dbnode.port if dbnode else 62050
                remote_api = dbnode.api_port if dbnode else 62051
            ensure_node_tunnel(
                job.node_id,
                creds.host,
                remote_port=remote_port,
                remote_api_port=remote_api,
                ssh_port=getattr(creds, "port", 22) or 22,
                username=getattr(creds, "username", "root") or "root",
            )
            xray_ops.connect_node(job.node_id)
        except Exception as exc:
            logger.warning(
                "Post-provision control tunnel/reconnect for node %s: %s",
                job.node_id,
                exc,
            )
    except Exception as exc:
        stop.set()
        err = _clip_provision_message(str(exc)) or str(exc)
        logger.warning("Provision job %s failed for node %s: %s", job_id, job.node_id, err)
        with _lock:
            job.status = "failed"
            job.error = err
            job.message = err
            job.step = "failed"
            job.finished_at = time.time()
            _extras.pop(job_id, None)
        _publish_job(job)
        try:
            _set_node_provision(
                job.node_id,
                status="failed",
                message=err,
                node_status=NodeStatus.error,
            )
        except Exception:
            logger.exception(
                "Failed to persist provision failure for node %s", job.node_id,
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
    force_image: bool = False,
    use_iran_mirror: bool = False,
) -> str:
    job_id = uuid.uuid4().hex
    job = ProvisionJob(id=job_id, node_id=node_id, node_name=node_name)
    with _lock:
        _jobs[job_id] = job
        _by_node[node_id] = job_id
        if extras is not None:
            _extras[job_id] = extras
    _publish_job(job)
    threading.Thread(
        target=_run_job,
        args=(job_id, creds, command, ssh_timeout, exec_timeout, force_image, use_iran_mirror),
        daemon=True,
    ).start()
    return job_id


def get_job(job_id: str) -> Optional[ProvisionJob]:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            return job
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(_REDIS_JOB.format(job_id))
        if not raw:
            return None
        data = json.loads(raw)
        return _job_from_payload(data) if isinstance(data, dict) else None
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def progress_for_node(node_id: int) -> Optional[ProvisionJob]:
    with _lock:
        jid = _by_node.get(node_id)
        job = _jobs.get(jid) if jid else None
        if job is not None:
            return job
    return _load_job_for_node(node_id)


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
    _publish_job(job)


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
