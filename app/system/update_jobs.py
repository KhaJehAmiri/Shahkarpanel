"""In-process panel update jobs (backup, git pull, build, service restart)."""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

JobStatus = Literal["pending", "running", "success", "failed"]
StepStatus = Literal["pending", "running", "done", "failed"]

_ROOT = Path(__file__).resolve().parents[2]
_VERSION_FILE = _ROOT / "VERSION"
_lock = threading.Lock()
_jobs: Dict[str, "UpdateJob"] = {}

STEP_ORDER = ("backup", "pull", "migrate", "build", "restart")


@dataclass
class UpdateStep:
    id: str
    status: StepStatus = "pending"
    detail: Optional[str] = None


@dataclass
class UpdateJob:
    id: str
    status: JobStatus = "pending"
    steps: List[UpdateStep] = field(default_factory=list)
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def _index(self, step_id: str) -> int:
        for i, s in enumerate(self.steps):
            if s.id == step_id:
                return i
        self.steps.append(UpdateStep(id=step_id))
        return len(self.steps) - 1

    def step_running(self, step_id: str) -> None:
        self.steps[self._index(step_id)].status = "running"

    def step_done(self, step_id: str, detail: Optional[str] = None) -> None:
        s = self.steps[self._index(step_id)]
        s.status = "done"
        if detail:
            s.detail = detail

    def step_failed(self, step_id: str, detail: Optional[str] = None) -> None:
        s = self.steps[self._index(step_id)]
        s.status = "failed"
        if detail:
            s.detail = detail


def _read_version_file(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    line = path.read_text(encoding="utf-8").strip().splitlines()
    if not line:
        return None
    m = re.match(r"^(\d+\.\d+\.\d+)$", line[0].strip())
    return m.group(1) if m else None


def _version_at_git_ref(ref: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "show", f"{ref}:VERSION"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        m = re.match(r"^(\d+\.\d+\.\d+)", out.strip())
        return m.group(1) if m else None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _local_version() -> str:
    return _read_version_file(_VERSION_FILE) or "0.0.0"


def _release_notes_for(version: str) -> str:
    changelog = _ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        return ""
    try:
        text = changelog.read_text(encoding="utf-8")
    except OSError:
        return ""
    pattern = rf"##\s+{re.escape(version)}\b[^\n]*\n(.*?)(?=\n##\s+|\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return ""
    lines = []
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if line.startswith("- "):
            lines.append(line[2:].strip())
    return "\n".join(lines[:8])


def _run_cmd_quiet(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600) -> None:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd or _ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("timeout")
    if proc.returncode != 0:
        msg = (err or "").strip().splitlines()
        raise RuntimeError(msg[-1] if msg else f"exit {proc.returncode}")


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _restart_panel(job: UpdateJob) -> None:
    compose_pg = _ROOT / "docker-compose.postgres.yml"
    compose_default = _ROOT / "docker-compose.yml"
    if _docker_available():
        if compose_pg.is_file():
            _run_cmd_quiet(
                ["docker", "compose", "-f", str(compose_pg), "restart", "nexuspanel"],
                timeout=180,
            )
            return
        if compose_default.is_file():
            _run_cmd_quiet(
                ["docker", "compose", "-f", str(compose_default), "restart", "nexuspanel"],
                timeout=180,
            )
            return
    for unit in ("nexuspanel", "marzban"):
        if not shutil.which("systemctl"):
            break
        try:
            _run_cmd_quiet(["systemctl", "restart", unit], timeout=120)
            return
        except RuntimeError:
            continue
    script = _ROOT / "scripts" / "restart_panel.sh"
    if script.is_file():
        _run_cmd_quiet(["bash", str(script)], timeout=60)
        return
    raise RuntimeError("restart_unavailable")


def _worker(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return
    job.status = "running"
    for sid in STEP_ORDER:
        job.steps.append(UpdateStep(id=sid, status="pending"))
    try:
        job.step_running("backup")
        from app.backup import create_backup

        path = create_backup()
        job.step_done("backup", detail=Path(path).name)

        job.step_running("pull")
        _run_cmd_quiet(["git", "fetch", "origin"])
        _run_cmd_quiet(["git", "pull", "origin", "master"])
        job.step_done("pull")

        job.step_running("migrate")
        _run_cmd_quiet(["alembic", "upgrade", "head"])
        job.step_done("migrate")

        job.step_running("build")
        build = _ROOT / "build_dashboard.sh"
        if build.is_file():
            _run_cmd_quiet(["bash", str(build)], timeout=900)
        job.step_done("build")

        job.step_running("restart")
        _restart_panel(job)
        job.step_done("restart")
        job.status = "success"
    except Exception as exc:
        job.error_message = str(exc)
        for s in job.steps:
            if s.status == "running":
                s.status = "failed"
                s.detail = str(exc)
                break
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
    """Compare installed semver to origin/master VERSION file."""
    current_version = _local_version()
    result = {
        "current_version": current_version,
        "remote_version": current_version,
        "current_sha": None,
        "remote_sha": None,
        "commits_behind": 0,
        "changelog_md": "",
        "release_notes": "",
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
        remote_version = _version_at_git_ref("origin/master") or current_version
        result["remote_version"] = remote_version
        if result["current_sha"] == result["remote_sha"]:
            result["release_notes"] = ""
            return result
        count_out = subprocess.check_output(
            ["git", "rev-list", "--count", f'{result["current_sha"]}..origin/master'],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        result["commits_behind"] = max(int(count_out or "0"), 1)
        notes = _release_notes_for(remote_version)
        result["release_notes"] = notes
        result["changelog_md"] = notes
        if "BREAKING" in notes.upper():
            result["breaking"] = True
    except (subprocess.SubprocessError, FileNotFoundError, OSError, ValueError):
        pass
    return result


def job_to_api(job: UpdateJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "finished": job.status in ("success", "failed"),
        "error_message": job.error_message,
        "steps": [
            {"id": s.id, "status": s.status, "detail": s.detail}
            for s in job.steps
        ],
    }
