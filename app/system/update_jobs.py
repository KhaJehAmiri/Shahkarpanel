"""In-process panel update jobs (backup, git pull, build, service restart)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

JobStatus = Literal["pending", "running", "success", "failed"]
StepStatus = Literal["pending", "running", "done", "failed"]
UpdateMode = Literal["restart", "pip", "dashboard", "rebuild"]

_ROOT = Path(__file__).resolve().parents[2]
_VERSION_FILE = _ROOT / "VERSION"
_META_FILE = Path(os.environ.get("NEXUSPANEL_DATA_DIR", "/var/lib/nexuspanel")) / "install-meta.json"
_COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
_lock = threading.Lock()
_jobs: Dict[str, "UpdateJob"] = {}

STEP_ORDER = ("pull", "backup", "migrate", "build", "restart")

_IMAGE_REBUILD_FILES = frozenset({"Dockerfile", "docker-entrypoint.sh"})
_PIP_FILES = frozenset({"requirements.txt"})


def _github_repo() -> str:
    try:
        from config import PANEL_GITHUB_REPO

        return PANEL_GITHUB_REPO.strip() or "KhaJehAmiri/nexuspanel"
    except Exception:
        return "KhaJehAmiri/nexuspanel"


def _github_branch() -> str:
    try:
        from config import PANEL_GITHUB_BRANCH

        return PANEL_GITHUB_BRANCH.strip() or "master"
    except Exception:
        return "master"


def _github_raw(path: str) -> str:
    branch = _github_branch()
    return f"https://raw.githubusercontent.com/{_github_repo()}/{branch}/{path.lstrip('/')}"


def _fetch_text(url: str, timeout: int = 20) -> Optional[str]:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace").strip()
    except (URLError, OSError, ValueError, TimeoutError):
        return None


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
    update_mode: UpdateMode = "restart"

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


def _write_install_meta(version: str, sha: Optional[str] = None) -> None:
    try:
        _META_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": version, "sha": sha, "updated_at": int(time.time())}
        _META_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _read_install_meta() -> dict:
    if not _META_FILE.is_file():
        return {}
    try:
        return json.loads(_META_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _version_at_git_ref(ref: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", *_GIT_SAFE, "show", f"{ref}:VERSION"],
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


def _remote_version_https() -> Optional[str]:
    raw = _fetch_text(_github_raw("VERSION"))
    if not raw:
        return None
    m = re.match(r"^(\d+\.\d+\.\d+)", raw.strip())
    return m.group(1) if m else None


def _remote_sha_https() -> Optional[str]:
    repo = _github_repo()
    branch = _github_branch()
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    try:
        with urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        sha = data.get("sha") or ""
        return sha[:7] if sha else None
    except (URLError, OSError, json.JSONDecodeError, ValueError, KeyError):
        return None


def _semver_tuple(version: str) -> tuple:
    parts = (version or "0.0.0").strip().split(".")
    nums: List[int] = []
    for part in parts[:3]:
        try:
            nums.append(int(re.sub(r"[^0-9].*", "", part) or "0"))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _release_notes_i18n(version: str) -> Dict[str, List[str]]:
    path = _ROOT / "release-notes" / f"{version}.json"
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                out: Dict[str, List[str]] = {}
                for lang, items in raw.items():
                    if isinstance(items, list):
                        out[str(lang)] = [str(x).strip() for x in items if str(x).strip()]
                    elif items:
                        out[str(lang)] = [str(items).strip()]
                if out:
                    return out
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    remote = _fetch_text(_github_raw(f"release-notes/{version}.json"))
    if remote:
        try:
            raw = json.loads(remote)
            if isinstance(raw, dict):
                out = {}
                for lang, items in raw.items():
                    if isinstance(items, list):
                        out[str(lang)] = [str(x).strip() for x in items if str(x).strip()]
                if out:
                    return out
        except json.JSONDecodeError:
            pass
    en = [ln.strip() for ln in _release_notes_for(version).split("\n") if ln.strip()]
    return {"en": en, "fa": en, "ru": en, "zh": en}


def _release_notes_for(version: str) -> str:
    changelog = _ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        remote = _fetch_text(_github_raw("CHANGELOG.md"))
        if remote:
            pattern = rf"##\s+{re.escape(version)}\b[^\n]*\n(.*?)(?=\n##\s+|\Z)"
            m = re.search(pattern, remote, re.DOTALL)
            if m:
                lines = [line[2:].strip() for line in m.group(1).splitlines() if line.strip().startswith("- ")]
                return "\n".join(lines[:8])
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


_GIT_SAFE = ("-c", f"safe.directory={_ROOT}")


def _git_available() -> bool:
    return shutil.which("git") is not None and (_ROOT / ".git").is_dir()


def _docker_available() -> bool:
    return Path("/var/run/docker.sock").exists() and shutil.which("docker") is not None


def _compose_file() -> Optional[Path]:
    for name in ("docker-compose.postgres.yml", "docker-compose.yml"):
        path = _ROOT / name
        if path.is_file():
            return path
    return None


def _compose_cmd(*args: str) -> List[str]:
    compose = _compose_file()
    if not compose:
        raise RuntimeError("docker_compose_unavailable")
    return [
        "docker",
        "compose",
        "-p",
        _COMPOSE_PROJECT,
        "-f",
        compose.name,
        *args,
    ]


def _git_head_sha() -> Optional[str]:
    if not _git_available():
        return None
    try:
        return subprocess.check_output(
            ["git", *_GIT_SAFE, "rev-parse", "HEAD"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _git_changed_files(from_sha: str, to_sha: str = "HEAD") -> List[str]:
    if not _git_available() or not from_sha:
        return []
    try:
        out = subprocess.check_output(
            ["git", *_GIT_SAFE, "diff", "--name-only", from_sha, to_sha],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []


def _dashboard_prebuilt() -> bool:
    return (_ROOT / "app" / "dashboard-next" / "out" / "dashboard" / "index.html").is_file()


def plan_update(changed: List[str]) -> Tuple[UpdateMode, str]:
    """Pick the smallest safe update path from a git diff file list."""
    if not changed:
        return "restart", "fast restart (bind-mounted code)"

    if any(name in _IMAGE_REBUILD_FILES for name in changed):
        return "rebuild", "Dockerfile/entrypoint changed"

    if any(name in _PIP_FILES for name in changed):
        return "pip", "requirements.txt changed"

    dash_src = any(p.startswith("app/dashboard-next/src/") for p in changed)
    dash_out = any(p.startswith("app/dashboard-next/out/") for p in changed)
    if dash_src and not dash_out and not _dashboard_prebuilt():
        return "dashboard", "dashboard source changed (no prebuilt out/)"

    return "restart", "app/config only (bind-mounted code)"


def _git_pull() -> None:
    branch = _github_branch()
    _run_cmd_quiet(["git", *_GIT_SAFE, "fetch", "origin", branch, "--depth", "1"])
    _run_cmd_quiet(["git", *_GIT_SAFE, "reset", "--hard", f"origin/{branch}"])


def _pip_install_requirements() -> None:
    req = _ROOT / "requirements.txt"
    if not req.is_file():
        return
    if _docker_available() and _compose_file():
        _run_cmd_quiet(
            _compose_cmd("exec", "-T", "-u", "0", "nexuspanel", "pip", "install", "--no-cache-dir", "-r", "/code/requirements.txt"),
            timeout=900,
        )
        return
    _run_cmd_quiet([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", str(req)], timeout=900)


def _build_dashboard() -> None:
    build = _ROOT / "build_dashboard.sh"
    if not build.is_file():
        raise RuntimeError("build_dashboard.sh missing")
    if shutil.which("npm"):
        _run_cmd_quiet(["bash", str(build)], timeout=900)
        return
    if not _dashboard_prebuilt():
        raise RuntimeError("npm unavailable and dashboard out/ is missing")


def _schedule_compose_action(mode: UpdateMode) -> None:
    """Run compose restart/rebuild detached so the API can report success first."""
    log_path = _META_FILE.parent / "update-rebuild.log"
    if mode == "rebuild":
        cmd = _compose_cmd("up", "-d", "--build", "nexuspanel")
        label = "rebuild"
    else:
        # Must restart the container — `up -d` alone leaves the old Python process running.
        cmd = _compose_cmd("restart", "nexuspanel")
        label = "restart"
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n--- {label} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} mode={mode} ---\n")
        logf.flush()
        subprocess.Popen(
            cmd,
            cwd=str(_ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _restart_panel(job: UpdateJob) -> None:
    if _docker_available() and _compose_file():
        _run_cmd_quiet(_compose_cmd("restart", "nexuspanel"), cwd=_ROOT, timeout=180)
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
    old_sha = _git_head_sha()
    use_docker = _docker_available() and bool(_compose_file())
    try:
        job.step_running("pull")
        if _git_available():
            _git_pull()
            job.step_done("pull", detail=f"origin/{_github_branch()}")
        else:
            raise RuntimeError(
                "git unavailable — bind-mount the app dir (/opt/nexuspanel:/code) and install git in the panel container"
            )

        job.step_running("backup")
        try:
            from app.backup import create_backup

            path = create_backup()
            job.step_done("backup", detail=Path(path).name)
        except Exception as exc:
            job.step_done("backup", detail=f"skipped: {exc}")

        changed = _git_changed_files(old_sha or "", "HEAD")
        mode, mode_detail = plan_update(changed)
        job.update_mode = mode

        job.step_running("migrate")
        _run_cmd_quiet(["alembic", "upgrade", "head"])
        job.step_done("migrate")

        job.step_running("build")
        if mode == "rebuild":
            job.step_done("build", detail=mode_detail)
        elif mode == "pip":
            _pip_install_requirements()
            job.step_done("build", detail=mode_detail)
        elif mode == "dashboard":
            _build_dashboard()
            job.step_done("build", detail=mode_detail)
        else:
            job.step_done("build", detail=mode_detail)

        new_ver = _local_version()
        sha = _git_head_sha()
        _write_install_meta(new_ver, sha)

        job.step_running("restart")
        if use_docker:
            job.step_done("restart", detail=f"{mode} scheduled")
        else:
            _restart_panel(job)
            job.step_done("restart")

        job.status = "success"
        if use_docker:
            time.sleep(2)
            _schedule_compose_action("rebuild" if mode == "rebuild" else "restart")
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


class UpdateInProgress(Exception):
    """Raised when an update job is already running."""


def start_apply_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    job = UpdateJob(id=job_id)
    with _lock:
        for existing in _jobs.values():
            if existing.status not in ("success", "failed"):
                raise UpdateInProgress(existing.id)
        _jobs[job_id] = job
    threading.Thread(target=_worker, args=(job_id,), daemon=True).start()
    return job_id


def get_job(job_id: str) -> Optional[UpdateJob]:
    with _lock:
        return _jobs.get(job_id)


def check_updates() -> dict:
    """Compare installed semver to GitHub master (git fetch or HTTPS fallback)."""
    current_version = _local_version()
    meta = _read_install_meta()
    result = {
        "current_version": current_version,
        "remote_version": current_version,
        "current_sha": meta.get("sha"),
        "remote_sha": None,
        "commits_behind": 0,
        "update_available": False,
        "check_source": "none",
        "changelog_md": "",
        "release_notes": "",
        "release_notes_i18n": {},
        "breaking": False,
    }

    remote_version = current_version
    remote_sha: Optional[str] = None
    commits_behind = 0
    git_ok = False

    if _git_available():
        try:
            branch = _github_branch()
            result["current_sha"] = (
                subprocess.check_output(
                    ["git", *_GIT_SAFE, "rev-parse", "--short", "HEAD"],
                    cwd=_ROOT,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
            )
            subprocess.check_call(
                ["git", *_GIT_SAFE, "fetch", "origin", branch, "--depth", "1"],
                cwd=_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            remote_sha = (
                subprocess.check_output(
                    ["git", *_GIT_SAFE, "rev-parse", "--short", f"origin/{branch}"],
                    cwd=_ROOT,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
            )
            remote_version = _version_at_git_ref(f"origin/{branch}") or _remote_version_https() or current_version
            if result["current_sha"] and remote_sha and result["current_sha"] != remote_sha:
                count_out = subprocess.check_output(
                    ["git", *_GIT_SAFE, "rev-list", "--count", f'HEAD..origin/{branch}'],
                    cwd=_ROOT,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                commits_behind = int(count_out or "0")
            git_ok = True
            result["check_source"] = "git"
        except (subprocess.SubprocessError, FileNotFoundError, OSError, ValueError):
            git_ok = False

    if not git_ok:
        https_ver = _remote_version_https()
        if https_ver:
            remote_version = https_ver
        remote_sha = _remote_sha_https()
        result["check_source"] = "github"
        if remote_sha and result.get("current_sha") and remote_sha != result["current_sha"]:
            commits_behind = 1

    semver_ahead = _semver_tuple(remote_version) > _semver_tuple(current_version)
    if semver_ahead and commits_behind == 0:
        commits_behind = 1
    if remote_sha and result.get("current_sha") and remote_sha != result["current_sha"] and commits_behind == 0:
        commits_behind = 1

    result["remote_version"] = remote_version
    result["remote_sha"] = remote_sha
    result["commits_behind"] = commits_behind
    result["update_available"] = semver_ahead or commits_behind > 0

    if result["update_available"]:
        notes_i18n = _release_notes_i18n(remote_version)
        result["release_notes_i18n"] = notes_i18n
        notes = notes_i18n.get("en") or []
        joined = "\n".join(notes)
        result["release_notes"] = joined
        result["changelog_md"] = joined
        if "BREAKING" in joined.upper():
            result["breaking"] = True

    return result


def job_to_api(job: UpdateJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "finished": job.status in ("success", "failed"),
        "error_message": job.error_message,
        "update_mode": job.update_mode,
        "steps": [
            {"id": s.id, "status": s.status, "detail": s.detail}
            for s in job.steps
        ],
    }
