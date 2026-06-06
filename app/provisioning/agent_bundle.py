"""Tarball of the node-agent source for remote ``docker build`` during SSH provision."""
import io
import tarfile
from pathlib import Path

NODE_AGENT_SRC = Path(__file__).resolve().parents[2] / "node"

_SKIP_SUFFIXES = {".pyc", ".pyo"}
_SKIP_DIRS = {"__pycache__", ".git"}


def iter_agent_files():
    """Yield (absolute_path, archive_name) pairs under ``node/``."""
    root = NODE_AGENT_SRC
    if not root.is_dir():
        raise FileNotFoundError(f"Node agent source not found: {root}")
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root.parent)
        parts = rel.parts
        if any(p in _SKIP_DIRS for p in parts):
            continue
        if path.suffix in _SKIP_SUFFIXES:
            continue
        yield path, rel.as_posix()


def build_agent_bundle() -> bytes:
    """Return a gzip tarball containing the ``node/`` directory tree."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for abs_path, arcname in iter_agent_files():
            tar.add(abs_path, arcname=arcname)
    return buf.getvalue()
