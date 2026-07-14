"""Serve a ``docker save`` of the node-agent image for SSH provision.

When the remote node's network blocks Docker Hub / CloudFront (HTTP 403 on
blob pulls), ``docker build`` on the node fails even though the panel bundle
downloaded fine. Shipping the panel's already-built ``nexuspanel/node`` image
avoids any Hub access on the node.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from config import NODE_AGENT_IMAGE

logger = logging.getLogger("uvicorn.error")

_CACHE_DIR = Path("/var/lib/nexuspanel/cache/agent-images")


class AgentImageUnavailable(RuntimeError):
    """Panel cannot produce a loadable node-agent image tarball."""


def _docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def image_id(image: Optional[str] = None) -> str:
    """Return the local image ID (sha256:…) or raise if missing."""
    ref = (image or NODE_AGENT_IMAGE).strip() or "nexuspanel/node:latest"
    proc = _docker("image", "inspect", "--format", "{{.Id}}", ref, timeout=30)
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        detail = (proc.stderr or proc.stdout or "").strip() or "not found"
        raise AgentImageUnavailable(
            f"Node agent image '{ref}' is not available on the panel host ({detail}). "
            f"Build it first: docker build -t {ref} /opt/nexuspanel/node"
        )
    return proc.stdout.strip()


def cached_image_path(image: Optional[str] = None) -> Path:
    """Return path to a gzipped ``docker save`` tarball, building the cache if needed."""
    ref = (image or NODE_AGENT_IMAGE).strip() or "nexuspanel/node:latest"
    iid = image_id(ref)
    short = iid.split(":", 1)[-1][:16]
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = _CACHE_DIR / f"{short}.tar.gz"
    if out.is_file() and out.stat().st_size > 0:
        return out

    for stale in _CACHE_DIR.glob("*.tar.gz"):
        if stale.name != out.name:
            try:
                stale.unlink()
            except OSError:
                pass

    tmp = out.with_suffix(".tar.gz.partial")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass

    logger.info("Caching docker save of %s (%s) → %s", ref, short, out)
    # docker save | gzip — ``docker load`` accepts gzip-compressed archives.
    try:
        with open(tmp, "wb") as fh:
            proc = subprocess.run(
                ["bash", "-c", f"docker save {shlex.quote(ref)} | gzip -c"],
                stdout=fh,
                stderr=subprocess.PIPE,
                timeout=600,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise AgentImageUnavailable(f"docker save failed: {exc}") from exc

    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise AgentImageUnavailable(
            f"docker save/gzip of '{ref}' failed: {detail or 'unknown error'}"
        )

    tmp.replace(out)
    return out
