"""In-process panel update jobs (backup, git pull, build, service restart)."""
from __future__ import annotations

import json
import os
import re
import shlex
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
UpdateMode = Literal["restart", "pip", "dashboard", "recreate", "rebuild"]

_ROOT = Path(__file__).resolve().parents[2]
_VERSION_FILE = _ROOT / "VERSION"
_META_FILE = Path(os.environ.get("NEXUSPANEL_DATA_DIR", "/var/lib/nexuspanel")) / "install-meta.json"
_COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
_lock = threading.Lock()
_jobs: Dict[str, "UpdateJob"] = {}

STEP_ORDER = ("pull", "backup", "migrate", "build", "restart")

_IMAGE_REBUILD_FILES = frozenset({"Dockerfile", "docker-entrypoint.sh"})
_PIP_FILES = frozenset({"requirements.txt"})
# Changing any of these alters the container's runtime shape (bind mounts,
# pid/network namespace, capabilities). A plain `docker restart` reuses the
# existing container's HostConfig, so those changes never take effect — the
# container must be recreated. This is exactly what silently broke subscription
# serving on custom ports: the compose file gained the nginx bind mounts, but
# updated panels only `docker restart`ed, so the running container had no nginx
# access and could never write the `:2096` vhost.
_COMPOSE_FILES = frozenset(
    {
        "docker-compose.yml",
        "docker-compose.postgres.yml",
        "docker-compose.monitoring.yml",
    }
)


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


def _fetch_text(url: str, timeout: int = 8) -> Optional[str]:
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
        with urlopen(url, timeout=8) as resp:
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

    if any(name in _COMPOSE_FILES for name in changed):
        return "recreate", "docker-compose changed (recreate for new mounts/caps/namespaces)"

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


def _own_container_id() -> Optional[str]:
    """Resolve this panel's own container id.

    ``$HOSTNAME``/cgroup are unreliable inside our container (compose sets a
    custom hostname; cgroup v2 exposes nothing), so ask compose for the id of
    the ``nexuspanel`` service while the container is still alive.
    """
    try:
        out = subprocess.check_output(
            _compose_cmd("ps", "-q", "nexuspanel"),
            cwd=str(_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).strip().splitlines()
    except (subprocess.SubprocessError, FileNotFoundError, OSError, RuntimeError):
        return None
    return out[0].strip() if out and out[0].strip() else None


def _open_update_log():
    """Open the update/restart log, best-effort — never block the restart on it.

    The panel process runs unprivileged (uid 1000), but the data dir
    (``/var/lib/nexuspanel``) is commonly ``root:root 0755``, so *creating* a
    new ``update-rebuild.log`` there raises ``PermissionError``. That used to
    abort ``_schedule_compose_action`` entirely — the pulled code landed on
    disk but the container was NEVER restarted, so the panel kept running the
    OLD in-memory version ("update says done but source didn't change"). Fall
    back to ``/tmp`` and finally to no log so the restart always proceeds.
    """
    for candidate in (_META_FILE.parent / "update-rebuild.log", Path("/tmp") / "nexuspanel-update-rebuild.log"):
        try:
            return open(candidate, "a", encoding="utf-8")
        except OSError:
            continue
    return None


def _own_image() -> Optional[str]:
    """Image ref of this panel container (for the self-update sidecar)."""
    cid = _own_container_id()
    if not cid:
        return None
    try:
        out = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.Config.Image}}", cid],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    return out or None


def _schedule_compose_action(mode: UpdateMode) -> None:
    """Restart/recreate the panel (detached) so Python reloads the pulled code.

    This runs *inside the very container being restarted*, which is why a plain
    ``compose up --force-recreate`` invoked here is unreliable: recreate is a
    multi-step, client-orchestrated operation — the moment it stops the old
    container, the orchestrating process (running inside it) is killed before
    the new container is created/started. The panel then keeps serving the OLD
    in-memory code even though ``/code`` already holds the new files (the exact
    "the update didn't take effect / no restart happened" bug).

    - ``restart`` (common, code-only): a single **atomic** ``docker restart
      <cid>`` — one daemon-side operation the daemon finishes even after the CLI
      is killed when the container goes down. With ``.:/code`` bind-mounted, a
      plain restart re-execs the entrypoint and imports the new code (and,
      unlike ``--force-recreate``, keeps any ``pip``-installed packages).
    - ``recreate``/``rebuild``: the container's runtime shape changed (compose
      mounts/caps/namespaces, or the image itself), which ``docker restart``
      can NOT apply — it reuses the old HostConfig. A recreate must survive the
      old container being torn down, so we launch it from a **detached sidecar
      container** (same image, own docker.sock + project dir) instead of a
      shell that dies with us. The sidecar runs ``compose up -d
      --force-recreate`` (``--build`` for rebuild) and outlives the swap.
    """
    cid = _own_container_id()

    label = mode
    if mode in ("recreate", "rebuild"):
        up_args = ["up", "-d", "--force-recreate", "--no-deps", "nexuspanel"]
        if mode == "rebuild":
            up_args.insert(2, "--build")
        image = _own_image()
        compose = _compose_file()
        if image and compose and Path("/var/run/docker.sock").exists():
            # Reliable path: a separate throwaway container does the recreate so
            # tearing down THIS container can't abort the operation midway.
            inner_compose = " ".join(
                shlex.quote(c)
                for c in ["docker", "compose", "-p", _COMPOSE_PROJECT, "-f", compose.name, *up_args]
            )
            cmd = [
                "docker", "run", "-d", "--rm",
                "--network", "none",
                "-v", "/var/run/docker.sock:/var/run/docker.sock",
                "-v", f"{_ROOT}:{_ROOT}",
                "-w", str(_ROOT),
                "--entrypoint", "sh",
                image,
                "-c", f"sleep 2; {inner_compose}",
            ]
        else:
            # Best effort if we can't resolve the image/socket: recreate inline.
            cmd = _compose_cmd(*up_args)
    elif cid:
        # Prefer a short SIGTERM grace over plain ``docker restart`` (10s default)
        # so :8000 comes back sooner after in-dashboard updates.
        cmd = [
            "sh", "-c",
            f"docker stop -t 3 {shlex.quote(cid)} && docker start {shlex.quote(cid)}",
        ]
    else:
        # No container id — fall back to compose recreate (best effort).
        cmd = _compose_cmd("up", "-d", "--force-recreate", "--no-deps", "nexuspanel")
        label = "recreate"

    # A short delay lets the update-job status flush before we go down.
    inner = "sleep 1; " + " ".join(shlex.quote(c) for c in cmd)
    # Logging is best-effort and MUST NOT prevent the restart (see
    # _open_update_log): if the log dir isn't writable we still spawn the
    # restart with output discarded, otherwise the update would silently never
    # take effect.
    logf = _open_update_log()
    try:
        if logf is not None:
            logf.write(
                f"\n--- {label} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
                f"mode={mode} cid={cid or '?'} ---\n"
            )
            logf.flush()
        subprocess.Popen(
            ["sh", "-c", inner],
            cwd=str(_ROOT),
            stdout=logf or subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        if logf is not None:
            logf.close()


def _restart_panel(job: UpdateJob) -> None:
    if _docker_available() and _compose_file():
        _schedule_compose_action("restart")
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
            time.sleep(3)
            # Preserve rebuild/recreate: a plain restart can't apply an image
            # rebuild or docker-compose shape changes (mounts/caps/namespaces).
            action: UpdateMode = mode if mode in ("rebuild", "recreate") else "restart"
            _schedule_compose_action(action)
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


# Cache the (network-bound) update check so opening the Updates modal is
# instant. The check does a `git fetch` + optional GitHub HTTPS calls which can
# be slow on filtered/poor networks; without caching, every modal open blocked
# the "Install update" button behind that latency.
_CHECK_TTL = 300.0  # a fresh result is reused for this long
_check_cache: Optional[dict] = None
_check_cache_at: float = 0.0
_check_lock = threading.Lock()
_check_refreshing = False


def _refresh_check_cache() -> dict:
    global _check_cache, _check_cache_at
    result = _compute_check_updates()
    with _check_lock:
        _check_cache = result
        _check_cache_at = time.time()
    return result


def _background_refresh_check() -> None:
    global _check_refreshing
    try:
        _refresh_check_cache()
    finally:
        with _check_lock:
            _check_refreshing = False


def check_updates(force: bool = False) -> dict:
    """Return the update check, served from cache with stale-while-revalidate.

    - Fresh cache (< ``_CHECK_TTL``): returned immediately, no network.
    - Stale cache: returned immediately while a background thread refreshes it,
      so the modal/button never blocks on ``git fetch``/GitHub latency.
    - No cache yet (first call): computed synchronously.
    """
    global _check_refreshing
    now = time.time()
    with _check_lock:
        cached = _check_cache
        age = now - _check_cache_at

    if not force and cached is not None:
        if age < _CHECK_TTL:
            return cached
        # Stale: trigger a single background refresh and return the stale copy.
        with _check_lock:
            if not _check_refreshing:
                _check_refreshing = True
                start = True
            else:
                start = False
        if start:
            threading.Thread(target=_background_refresh_check, daemon=True).start()
        return cached

    # No cache (or forced): must compute now.
    return _refresh_check_cache()


def _compute_check_updates() -> dict:
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
            # Hard timeout: on a filtered/slow network a fetch to github.com can
            # otherwise hang for minutes, blocking the whole check (and the
            # Install button). Failing fast falls through to the HTTPS path.
            subprocess.check_call(
                ["git", *_GIT_SAFE, "fetch", "origin", branch, "--depth", "1"],
                cwd=_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=12,
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
