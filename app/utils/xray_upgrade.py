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
) -> str:
    tag = (tag or "").strip()
    if not tag:
        raise ValueError("tag required")
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
        shutil.copy2(bin_src, executable_path)
        os.chmod(executable_path, 0o755)
        for name in os.listdir(tmp):
            if name.endswith(".dat"):
                shutil.copy2(os.path.join(tmp, name), os.path.join(assets_path, name))
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
