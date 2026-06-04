"""In-process panel update jobs (backup, git pull, build, service restart)."""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

JobStatus = Literal["pending", "running", "success", "failed"]

_ROOT = Path(__file__).resolve().parents[2]
_lock = threading.Lock()
_jobs: Dict[str, "UpdateJob"] = {}


@dataclass
class UpdateJob:
    id: str
    status: JobStatus = "pending"
    log: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def append(self, line: str) -> None:
        self.log.append(line.rstrip())


def _run_cmd(job: UpdateJob, cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600) -> None:
    job.append(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd or _ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        job.append(line)
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"command timed out after {timeout}s")
    if code != 0:
        raise RuntimeError(f"command failed with exit {code}")


def _restart_panel(job: UpdateJob) -> None:
    compose_pg = _ROOT / "docker-compose.postgres.yml"
    compose_default = _ROOT / "docker-compose.yml"
    if compose_pg.is_file():
        _run_cmd(job, ["docker", "compose", "-f", str(compose_pg), "restart", "nexuspanel"], timeout=180)
        return
    if compose_default.is_file():
        _run_cmd(job, ["docker", "compose", "-f", str(compose_default), "restart", "nexuspanel"], timeout=180)
        return
    for unit in ("nexuspanel", "marzban", "nexuspanel.service"):
        try:
            _run_cmd(job, ["systemctl", "restart", unit], timeout=120)
            job.append(f"restarted systemd unit {unit}")
            return
        except RuntimeError:
            continue
    job.append("no docker compose or systemd unit found — restart panel process manually")


def _worker(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return
    job.status = "running"
    try:
        job.append("Creating pre-update backup...")
        from app.backup import create_backup

        path = create_backup()
        job.append(f"Backup: {path}")

        _run_cmd(job, ["git", "fetch", "origin"])
        _run_cmd(job, ["git", "pull", "origin", "master"])
        _run_cmd(job, ["alembic", "upgrade", "head"])
        bump = _ROOT / "scripts" / "bump_version.py"
        if bump.is_file():
            job.append("Bumping patch version...")
            _run_cmd(job, ["python3", str(bump), "patch"])
        build = _ROOT / "build_dashboard.sh"
        if build.is_file():
            _run_cmd(job, ["bash", str(build)], timeout=900)
        job.append("Restarting panel service...")
        _restart_panel(job)
        job.status = "success"
    except Exception as exc:
        job.append(f"ERROR: {exc}")
        job.status = "failed"
    finally:
        job.finished_at = time.time()


def start_apply_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    job = UpdateJob(id=job_id)
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_worker, args=(job_id,), daemon=True).start()
    return job_id


def get_job(job_id: str) -> Optional[UpdateJob]:
    with _lock:
        return _jobs.get(job_id)


def check_updates() -> dict:
    """Compare local HEAD to origin/master when git remote is configured."""
    result = {
        "current_sha": None,
        "remote_sha": None,
        "commits_behind": 0,
        "changelog_md": "",
        "breaking": False,
    }
    try:
        result["current_sha"] = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=_ROOT,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )
        subprocess.check_call(
            ["git", "fetch", "origin"],
            cwd=_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result["remote_sha"] = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "origin/master"],
                cwd=_ROOT,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )
        if result["current_sha"] == result["remote_sha"]:
            return result
        log = subprocess.check_output(
            ["git", "log", "--oneline", f'{result["current_sha"]}..origin/master'],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        lines = [ln for ln in log.splitlines() if ln.strip()][:20]
        result["commits_behind"] = max(len(lines), 1)
        result["changelog_md"] = "\n".join(lines)
        if any("BREAKING" in ln.upper() or "breaking" in ln for ln in lines):
            result["breaking"] = True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return result
