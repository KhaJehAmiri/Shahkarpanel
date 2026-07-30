"""Fleet / single-node agent image updates from the panel (SSH refresh)."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import provisioning
from app.db import GetDB, crud
from app.provisioning.iran_mirror import mirror_url_configured
from app.provisioning.node_ssh import resolve_node_ssh_candidates
from config import (
    NODE_AGENT_IMAGE,
    NODE_AGENT_PACKAGE_URL,
    NODE_BOOTSTRAP_TOKEN,
    NODE_CONTROL_SECRET,
    NODE_DEFAULT_API_PORT,
    NODE_DEFAULT_PORT,
    NODE_PROVISION_EXEC_TIMEOUT,
    NODE_PROVISION_SSH_TIMEOUT,
)

logger = logging.getLogger("shahkar-agent-update")

# Nodes often listen on 2222 (panel default remains 22). Remember the last
# working port per host so fleet updates do not re-probe forever.
_SSH_PORT_CACHE = Path(
    os.environ.get("SHAHKAR_DATA_DIR", "/var/lib/shahkar")
) / "secrets" / "node_ssh_ports.json"
# Also try the pre-rebrand data dir when the new path is not mounted.
_SSH_PORT_CACHE_LEGACY = Path("/var/lib/nexuspanel/secrets/node_ssh_ports.json")

JobStatus = Literal["pending", "running", "success", "failed", "partial"]
NodeStatus = Literal["pending", "running", "success", "failed", "skipped"]

_MAX_PARALLEL = 2
_CHECK_TTL = 120.0

_lock = threading.Lock()
_jobs: Dict[str, "AgentUpdateJob"] = {}
_check_cache: Optional[dict] = None
_check_cache_at: float = 0.0


class AgentUpdateInProgress(Exception):
    """Raised when an agent-update job is already running."""


@dataclass
class NodeUpdateStep:
    node_id: int
    node_name: str
    host: str
    status: NodeStatus = "pending"
    message: Optional[str] = None
    error: Optional[str] = None


@dataclass
class AgentUpdateJob:
    id: str
    status: JobStatus = "pending"
    message: Optional[str] = None
    error_message: Optional[str] = None
    nodes: List[NodeUpdateStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    @property
    def finished(self) -> bool:
        return self.status in ("success", "failed", "partial")


def _probe_package_url(url: str, timeout: float = 12.0) -> dict:
    """HEAD (then GET range) the agent package; return reachability metadata."""
    info = {
        "url": url,
        "reachable": False,
        "etag": None,
        "last_modified": None,
        "content_length": None,
        "error": None,
    }
    if not url:
        info["error"] = "NODE_AGENT_PACKAGE_URL is not configured"
        return info
    for method in ("HEAD", "GET"):
        try:
            req = Request(url, method=method)
            if method == "GET":
                req.add_header("Range", "bytes=0-0")
            with urlopen(req, timeout=timeout) as resp:
                info["reachable"] = 200 <= getattr(resp, "status", 200) < 400
                headers = getattr(resp, "headers", None) or {}
                info["etag"] = headers.get("ETag") or headers.get("etag")
                info["last_modified"] = headers.get("Last-Modified") or headers.get(
                    "last-modified"
                )
                cl = headers.get("Content-Length") or headers.get("content-length")
                if cl and cl.isdigit():
                    info["content_length"] = int(cl)
                return info
        except HTTPError as exc:
            if method == "HEAD" and exc.code in (403, 405):
                continue
            info["error"] = f"HTTP {exc.code}"
            return info
        except (URLError, OSError, TimeoutError) as exc:
            info["error"] = str(exc)[:200]
            return info
    return info


def _node_host(dbnode) -> str:
    return (getattr(dbnode, "provision_host", None) or dbnode.address or "").strip()


def _ssh_configured_for_host(host: str) -> bool:
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return False
    try:
        return bool(resolve_node_ssh_candidates(host))
    except Exception:
        return False


def _eligible_nodes() -> List[dict]:
    """Registered (or connected) nodes with an SSH host target."""
    out: List[dict] = []
    with GetDB() as db:
        for n in crud.get_nodes(db):
            host = _node_host(n)
            prov = (n.provision_status or "").strip().lower()
            if prov == "provisioning":
                continue
            if prov in ("failed",) and not host:
                continue
            # Skip placeholders that never got a host.
            if not host:
                out.append(
                    {
                        "id": n.id,
                        "name": n.name,
                        "host": "",
                        "eligible": False,
                        "reason": "no_host",
                        "core_kind": n.core_kind,
                        "region": n.region,
                        "status": str(n.status),
                    }
                )
                continue
            has_ssh = _ssh_configured_for_host(host)
            out.append(
                {
                    "id": n.id,
                    "name": n.name,
                    "host": host,
                    "eligible": has_ssh,
                    "reason": None if has_ssh else "no_ssh",
                    "core_kind": n.core_kind,
                    "region": n.region,
                    "status": str(n.status),
                }
            )
    return out


def check_agent_updates(force: bool = False) -> dict:
    global _check_cache, _check_cache_at
    now = time.time()
    if not force and _check_cache is not None and (now - _check_cache_at) < _CHECK_TTL:
        return _check_cache

    primary = (NODE_AGENT_PACKAGE_URL or "").strip()
    mirror = mirror_url_configured()
    pkg = _probe_package_url(primary)
    mirror_info = _probe_package_url(mirror) if mirror else None

    nodes = _eligible_nodes()
    eligible = [n for n in nodes if n["eligible"]]
    skipped = [n for n in nodes if not n["eligible"]]

    result = {
        "package_url": primary,
        "package_reachable": bool(pkg.get("reachable")),
        "package_etag": pkg.get("etag"),
        "package_last_modified": pkg.get("last_modified"),
        "package_error": pkg.get("error"),
        "mirror_url": mirror,
        "mirror_reachable": bool(mirror_info and mirror_info.get("reachable"))
        if mirror
        else False,
        "agent_image": NODE_AGENT_IMAGE,
        "nodes_total": len(nodes),
        "nodes_eligible": len(eligible),
        "nodes_skipped": len(skipped),
        "update_available": bool(pkg.get("reachable") or (mirror_info and mirror_info.get("reachable")))
        and len(eligible) > 0,
        "nodes": nodes,
        "ssh_available": provisioning.ssh_available(),
        "checked_at": int(now),
    }
    _check_cache = result
    _check_cache_at = now
    return result


def _client_cert_pem() -> Optional[str]:
    try:
        from app.xray.operations import get_tls

        return get_tls().get("certificate")
    except Exception:
        return None


def _agent_image_urls() -> tuple[str, Optional[str]]:
    primary = (NODE_AGENT_PACKAGE_URL or "").strip()
    mirror = mirror_url_configured()
    return primary, mirror


def _build_refresh_for_node(dbnode, *, force: bool) -> str:
    if not NODE_BOOTSTRAP_TOKEN:
        raise provisioning.ProvisioningError("NODE_BOOTSTRAP_TOKEN is not set")
    panel_url = provisioning.resolve_panel_public_url()
    image_url, mirror_url = _agent_image_urls()
    return provisioning.build_agent_refresh_command(
        panel_url,
        NODE_BOOTSTRAP_TOKEN,
        dbnode.name,
        tenant_id=dbnode.tenant_id,
        role=dbnode.role or "direct",
        core_kind=dbnode.core_kind or "xray",
        region=dbnode.region,
        image=NODE_AGENT_IMAGE,
        node_port=dbnode.port or NODE_DEFAULT_PORT,
        node_api_port=dbnode.api_port or NODE_DEFAULT_API_PORT,
        control_secret=NODE_CONTROL_SECRET or None,
        force_image_rebuild=force,
        client_cert_pem=_client_cert_pem(),
        agent_image_url=image_url,
        agent_image_mirror_url=mirror_url,
    )


def _ssh_port_cache_path() -> Path:
    if _SSH_PORT_CACHE.parent.is_dir():
        return _SSH_PORT_CACHE
    if _SSH_PORT_CACHE_LEGACY.parent.is_dir():
        return _SSH_PORT_CACHE_LEGACY
    return _SSH_PORT_CACHE


def _remembered_ssh_port(host: str) -> Optional[int]:
    path = _ssh_port_cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get(host)
        return int(raw) if raw else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _remember_ssh_port(host: str, port: int) -> None:
    path = _ssh_port_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        data[host] = int(port)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


def _ssh_ports(preferred: Optional[int] = None) -> List[int]:
    """SSH ports to try for agent maintenance (env → remembered → 22 → 2222)."""
    ports: List[int] = []
    for raw in (
        preferred,
        os.environ.get("NODE_SSH_PORT"),
        os.environ.get("WG_NODE_SSH_PORT"),
        22,
        2222,
    ):
        if raw is None or raw == "":
            continue
        try:
            port = int(raw)
        except (TypeError, ValueError):
            continue
        if port > 0 and port not in ports:
            ports.append(port)
    return ports or [22]


def _tcp_open(host: str, port: int, timeout: float = 2.5) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _try_ssh_candidates(host: str, port: Optional[int] = None, username: str = "root"):
    last_exc: Optional[BaseException] = None
    saw_creds = False
    preferred = port if port and port != 22 else _remembered_ssh_port(host)
    ordered = _ssh_ports(preferred)
    if preferred and preferred in ordered:
        ordered = [preferred] + [p for p in ordered if p != preferred]
    # Prefer ports that actually accept TCP so a firewalled :22 does not burn
    # the full SSH timeout before we try :2222.
    reachable = [p for p in ordered if _tcp_open(host, p)]
    ordered = reachable + [p for p in ordered if p not in reachable]

    for ssh_port in ordered:
        try:
            candidates = resolve_node_ssh_candidates(host, port=ssh_port, username=username)
        except FileNotFoundError:
            continue
        saw_creds = True
        for creds in candidates:
            try:
                provisioning.run_remote_command(
                    creds,
                    "true",
                    timeout=min(NODE_PROVISION_SSH_TIMEOUT, 15),
                    exec_timeout=30,
                )
                _remember_ssh_port(host, ssh_port)
                return creds
            except Exception as exc:
                last_exc = exc
                continue
    if last_exc:
        raise provisioning.ProvisioningError(
            f"SSH failed for {host}: {last_exc}. "
            "Install the panel control key on the node or set WG_NODE_SSH_PASSWORD."
        ) from last_exc
    raise provisioning.ProvisioningError(
        f"No SSH credentials configured for {host}. "
        "Set NODE_SSH_KEY_FILE / WG_NODE_SSH_PASSWORD or re-provision the node."
    )


def _update_one_node(step: NodeUpdateStep) -> None:
    step.status = "running"
    step.message = "Connecting over SSH…"
    try:
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, step.node_id)
            if not dbnode:
                raise provisioning.ProvisioningError("Node not found")
            host = _node_host(dbnode) or step.host
            step.host = host
            command = _build_refresh_for_node(dbnode, force=True)

        creds = _try_ssh_candidates(host)
        try:
            provisioning.install_control_pubkey(creds, timeout=NODE_PROVISION_SSH_TIMEOUT)
        except Exception:
            logger.debug("install_control_pubkey skipped for node %s", step.node_id)

        step.message = "Downloading / loading agent image…"
        try:
            provisioning.run_remote_command(
                creds,
                command,
                timeout=NODE_PROVISION_SSH_TIMEOUT,
                exec_timeout=NODE_PROVISION_EXEC_TIMEOUT,
            )
        except provisioning.ProvisioningError as exc:
            if not provisioning.is_agent_image_fetch_error(exc):
                raise
            step.message = "GitHub/mirror failed — uploading image via SSH…"
            logger.warning(
                "Agent image fetch failed on node %s; SSH upload fallback: %s",
                step.node_id,
                exc,
            )
            provisioning.push_agent_image_via_ssh(
                creds,
                force=True,
                timeout=NODE_PROVISION_SSH_TIMEOUT,
                transfer_timeout=min(NODE_PROVISION_EXEC_TIMEOUT, 1800),
            )
            step.message = "Restarting agent…"
            soft = provisioning.soft_restart_agent_command(command)
            provisioning.run_remote_command(
                creds,
                soft,
                timeout=NODE_PROVISION_SSH_TIMEOUT,
                exec_timeout=NODE_PROVISION_EXEC_TIMEOUT,
            )

        step.message = "Reconnecting…"
        try:
            from app.control_tunnel import ensure_node_tunnel
            from app.xray import operations as xray_ops

            with GetDB() as db:
                dbnode = crud.get_node_by_id(db, step.node_id)
                remote_port = dbnode.port if dbnode else NODE_DEFAULT_PORT
                remote_api = dbnode.api_port if dbnode else NODE_DEFAULT_API_PORT
            ensure_node_tunnel(
                step.node_id,
                host,
                remote_port=remote_port,
                remote_api_port=remote_api,
                ssh_port=getattr(creds, "port", 22) or 22,
                username=getattr(creds, "username", "root") or "root",
            )
            xray_ops.connect_node(step.node_id)
        except Exception as exc:
            logger.warning(
                "Post-agent-update reconnect for node %s: %s", step.node_id, exc
            )

        step.status = "success"
        step.message = "Agent updated"
        step.error = None
        try:
            from app.wireguard.finalmask_reload import clear_agent_hot_cache

            clear_agent_hot_cache(step.node_id)
        except Exception:
            logger.debug(
                "clear_agent_hot_cache after update node %s failed",
                step.node_id,
                exc_info=True,
            )
    except Exception as exc:
        step.status = "failed"
        step.error = str(exc)[:800]
        step.message = step.error
        logger.warning("Agent update failed for node %s: %s", step.node_id, exc)


def _worker(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.message = "Updating node agents…"

    targets = [s for s in job.nodes if s.status == "pending"]
    if not targets:
        with _lock:
            job.status = "failed"
            job.error_message = "No eligible nodes to update"
            job.finished_at = time.time()
        return

    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
        futures = {pool.submit(_update_one_node, step): step for step in targets}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                step = futures[fut]
                if step.status != "failed":
                    step.status = "failed"
                    step.error = "internal error"

    ok = sum(1 for s in job.nodes if s.status == "success")
    failed = sum(1 for s in job.nodes if s.status == "failed")
    skipped = sum(1 for s in job.nodes if s.status == "skipped")
    with _lock:
        if failed and ok:
            job.status = "partial"
            job.message = f"Updated {ok}; {failed} failed; {skipped} skipped"
        elif failed and not ok:
            job.status = "failed"
            job.error_message = f"All {failed} node update(s) failed"
            job.message = job.error_message
        else:
            job.status = "success"
            job.message = f"Updated {ok} node agent(s)"
        job.finished_at = time.time()


def _assert_no_running() -> None:
    with _lock:
        for existing in _jobs.values():
            if existing.status in ("pending", "running"):
                raise AgentUpdateInProgress(existing.id)


def start_fleet_apply() -> str:
    if not provisioning.ssh_available():
        raise provisioning.ProvisioningUnavailable(
            "SSH provisioning is unavailable (paramiko not installed)."
        )
    _assert_no_running()
    nodes = _eligible_nodes()
    steps: List[NodeUpdateStep] = []
    for n in nodes:
        step = NodeUpdateStep(
            node_id=n["id"],
            node_name=n["name"],
            host=n["host"] or "",
        )
        if not n["eligible"]:
            step.status = "skipped"
            step.message = (
                "No SSH credentials on panel for this host"
                if n["reason"] == "no_ssh"
                else "Node has no provision host / address"
            )
        steps.append(step)

    if not any(s.status == "pending" for s in steps):
        raise provisioning.ProvisioningError(
            "No nodes are eligible for agent update "
            "(need panel SSH key/password for each host)."
        )

    job_id = uuid.uuid4().hex[:12]
    job = AgentUpdateJob(id=job_id, nodes=steps)
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_worker, args=(job_id,), daemon=True).start()
    return job_id


def start_node_apply(node_id: int) -> str:
    if not provisioning.ssh_available():
        raise provisioning.ProvisioningUnavailable(
            "SSH provisioning is unavailable (paramiko not installed)."
        )
    _assert_no_running()
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if not dbnode:
            raise provisioning.ProvisioningError("Node not found")
        host = _node_host(dbnode)
        name = dbnode.name
        if (dbnode.provision_status or "").strip().lower() == "provisioning":
            raise provisioning.ProvisioningError(
                "Node is currently provisioning; wait for it to finish."
            )

    if not host:
        raise provisioning.ProvisioningError("Node has no provision host / address")
    if not _ssh_configured_for_host(host):
        raise provisioning.ProvisioningError(
            f"No SSH credentials configured for {host}. "
            "Set NODE_SSH_KEY_FILE / WG_NODE_SSH_PASSWORD or re-provision the node."
        )

    job_id = uuid.uuid4().hex[:12]
    job = AgentUpdateJob(
        id=job_id,
        nodes=[NodeUpdateStep(node_id=node_id, node_name=name, host=host)],
    )
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_worker, args=(job_id,), daemon=True).start()
    return job_id


def get_job(job_id: str) -> Optional[AgentUpdateJob]:
    with _lock:
        return _jobs.get(job_id)


def job_to_api(job: AgentUpdateJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "finished": job.finished,
        "message": job.message,
        "error_message": job.error_message,
        "nodes": [
            {
                "node_id": s.node_id,
                "node_name": s.node_name,
                "host": s.host,
                "status": s.status,
                "message": s.message,
                "error": s.error,
            }
            for s in job.nodes
        ],
    }
