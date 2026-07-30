"""Install Xray-core releases on the panel host (same logic as node agent)."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from typing import Optional
from urllib.request import urlopen

DEFAULT_EXECUTABLE = "/usr/local/bin/xray"
DEFAULT_ASSETS = "/usr/local/share/xray"


def _stop_running_xray(executable_path: str) -> None:
    """Stop panel-local Xray and any orphan using the same binary path."""
    try:
        from app import xray

        if xray.core.started:
            xray.core.stop()
    except Exception:
        pass
    try:
        from app.xray.core import XRayCore, find_stdin_xray_pids

        pids = find_stdin_xray_pids(executable_path)
        if pids:
            XRayCore._terminate_pids(pids)
            return
    except Exception:
        pass
    try:
        import psutil

        victims = []
        for proc in psutil.process_iter(["exe", "cmdline"]):
            try:
                info = proc.info
                exe = info.get("exe") or ""
                cmd = info.get("cmdline") or []
            except (psutil.Error, KeyError):
                continue
            if exe == executable_path or (
                len(cmd) >= 2 and cmd[0] == executable_path and cmd[1] == "run"
            ):
                proc.terminate()
                victims.append(proc)
        if victims:
            psutil.wait_procs(victims, timeout=5)
    except ImportError:
        subprocess.run(
            ["pkill", "-f", f"{executable_path} run"],
            check=False,
            timeout=10,
        )


def _atomic_replace_file(src: str, dest: str, *, mode: int = 0o755) -> None:
    """Replace ``dest`` safely so a live process never blocks the write.

    Prefers same-directory atomic rename. When the panel runs as a non-root
    user (Docker ``runuser -u shahkar``), ``/usr/local/bin`` is not
    writable — stage in a temp dir and overwrite ``dest`` in place instead
    (requires the binary/assets to be owned by the panel user; see
    ``fix_runtime_permissions`` in docker-entrypoint.sh).
    """
    dest_dir = os.path.dirname(os.path.abspath(dest)) or "."
    os.makedirs(dest_dir, exist_ok=True)
    staging_dir = dest_dir if os.access(dest_dir, os.W_OK) else None
    fd, tmp_path = tempfile.mkstemp(prefix=".xray-install-", dir=staging_dir)
    try:
        with os.fdopen(fd, "wb") as out_fh, open(src, "rb") as in_fh:
            shutil.copyfileobj(in_fh, out_fh)
        os.chmod(tmp_path, mode)
        try:
            os.replace(tmp_path, dest)
            tmp_path = ""  # owned by dest now
            return
        except OSError:
            # Cross-device rename or no write on dest_dir — overwrite in place.
            shutil.copyfile(tmp_path, dest)
            os.chmod(dest, mode)
    except Exception:
        raise
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _linux_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "64"
    if machine in ("aarch64", "arm64"):
        return "arm64-v8a"
    if machine.startswith("armv7"):
        return "arm32-v7a"
    return "64"


def _ensure_writable_install_paths(
    executable_path: str, assets_path: str
) -> tuple[str, str]:
    """Fall back to ``/var/lib/shahkar/...`` when system paths are root-only.

    Directory write is required (not just file write): replacing a running
    binary needs unlink/rename in the destination directory. The panel process
    runs as ``shahkar``, so ``/usr/local/bin`` is typically not usable.
    """
    exe_dir = os.path.dirname(os.path.abspath(executable_path)) or "/usr/local/bin"
    if not os.access(exe_dir, os.W_OK):
        fallback_exe = "/var/lib/shahkar/bin/xray"
        os.makedirs(os.path.dirname(fallback_exe), exist_ok=True)
        if os.path.isfile(executable_path) and not os.path.isfile(fallback_exe):
            try:
                shutil.copy2(executable_path, fallback_exe)
                os.chmod(fallback_exe, 0o755)
            except OSError:
                pass
        executable_path = fallback_exe

    assets_dir = assets_path if os.path.isdir(assets_path) else (
        os.path.dirname(os.path.abspath(assets_path)) or "/"
    )
    if not os.access(assets_dir, os.W_OK):
        fallback_assets = "/var/lib/shahkar/share/xray"
        os.makedirs(fallback_assets, exist_ok=True)
        if os.path.isdir(assets_path):
            for name in os.listdir(assets_path):
                if not name.endswith(".dat"):
                    continue
                src = os.path.join(assets_path, name)
                dest = os.path.join(fallback_assets, name)
                if os.path.isfile(src) and not os.path.isfile(dest):
                    try:
                        shutil.copy2(src, dest)
                    except OSError:
                        pass
        assets_path = fallback_assets
    else:
        os.makedirs(assets_path, exist_ok=True)
    return executable_path, assets_path


def install_xray_release(
    tag: str,
    executable_path: str = DEFAULT_EXECUTABLE,
    assets_path: str = DEFAULT_ASSETS,
    *,
    stop_running: bool = True,
) -> str:
    tag = (tag or "").strip()
    if not tag:
        raise ValueError("tag required")
    try:
        from config import XRAY_ASSETS_PATH, XRAY_EXECUTABLE_PATH

        if executable_path == DEFAULT_EXECUTABLE:
            executable_path = XRAY_EXECUTABLE_PATH
        if assets_path == DEFAULT_ASSETS:
            assets_path = XRAY_ASSETS_PATH
    except Exception:
        pass
    requested_exe = executable_path
    requested_assets = assets_path
    executable_path, assets_path = _ensure_writable_install_paths(
        executable_path, assets_path
    )
    if stop_running:
        _stop_running_xray(executable_path)
        if executable_path != requested_exe:
            _stop_running_xray(requested_exe)
    url = f"https://github.com/XTLS/Xray-core/releases/download/{tag}/Xray-linux-{_linux_arch()}.zip"
    os.makedirs(os.path.dirname(executable_path) or "/usr/local/bin", exist_ok=True)
    os.makedirs(assets_path, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "xray.zip")
        with urlopen(url, timeout=120) as resp, open(zip_path, "wb") as out:
            shutil.copyfileobj(resp, out)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        bin_src = os.path.join(tmp, "xray")
        if not os.path.isfile(bin_src):
            raise FileNotFoundError(f"xray binary missing in {tag} archive")
        _atomic_replace_file(bin_src, executable_path)
        for name in os.listdir(tmp):
            if name.endswith(".dat"):
                dest_dat = os.path.join(assets_path, name)
                _atomic_replace_file(os.path.join(tmp, name), dest_dat, mode=0o644)
    # If we had to install outside the configured path, point the live core at it
    # so the subsequent restart uses the binary we just wrote.
    if executable_path != requested_exe or assets_path != requested_assets:
        try:
            from app import xray as xray_pkg

            xray_pkg.core.executable_path = executable_path
            xray_pkg.core.assets_path = assets_path
            xray_pkg.core._env["XRAY_LOCATION_ASSET"] = assets_path
        except Exception:
            pass
    out = subprocess.check_output(
        [executable_path, "version"],
        stderr=subprocess.STDOUT,
        timeout=15,
        text=True,
    )
    line = out.strip().splitlines()[0] if out else tag
    try:
        from app.utils.xray_releases import normalize_xray_version_label

        return normalize_xray_version_label(line) or line
    except Exception:
        return line


def read_version(executable_path: str = DEFAULT_EXECUTABLE) -> Optional[str]:
    if not os.path.isfile(executable_path):
        return None
    try:
        out = subprocess.check_output(
            [executable_path, "version"],
            stderr=subprocess.STDOUT,
            timeout=10,
            text=True,
        )
        return out.strip().splitlines()[0] if out else None
    except (subprocess.SubprocessError, OSError):
        return None
