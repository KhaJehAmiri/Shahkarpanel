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
    """Replace ``dest`` atomically so a live process never blocks the write."""
    dest_dir = os.path.dirname(os.path.abspath(dest)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".xray-install-", dir=dest_dir)
    try:
        with os.fdopen(fd, "wb") as out_fh, open(src, "rb") as in_fh:
            shutil.copyfileobj(in_fh, out_fh)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, dest)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _linux_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "64"
    if machine in ("aarch64", "arm64"):
        return "arm64-v8a"
    if machine.startswith("armv7"):
        return "arm32-v7a"
    return "64"


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
    if stop_running:
        _stop_running_xray(executable_path)
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
    out = subprocess.check_output(
        [executable_path, "version"],
        stderr=subprocess.STDOUT,
        timeout=15,
        text=True,
    )
    return out.strip().splitlines()[0] if out else tag


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
