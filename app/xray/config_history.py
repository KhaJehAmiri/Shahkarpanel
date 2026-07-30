"""Rotating snapshots of the Xray master config, captured before each save.

``xray run -test`` validates a config's *shape*, but it cannot catch every
runtime problem (e.g. a port that binds fine under -test but conflicts once the
core actually starts). These snapshots let the panel auto-roll-back on a failed
restart and let an operator manually restore a previous known-good config.

Pure filesystem helpers (no DB), so they are easy to unit test.
"""
import json
import os
import time
from typing import List, Optional

from app import logger
from config import XRAY_JSON

_DEFAULT_HISTORY_DIR = "/var/lib/shahkar/xray-config-history"
HISTORY_DIR = os.environ.get("XRAY_CONFIG_HISTORY_DIR") or _DEFAULT_HISTORY_DIR
try:
    MAX_SNAPSHOTS = int(os.environ.get("XRAY_CONFIG_HISTORY_MAX", "20") or 20)
except ValueError:
    MAX_SNAPSHOTS = 20


def snapshot_config(raw: str) -> Optional[str]:
    """Persist ``raw`` (the current config file content) as a new snapshot.

    Best-effort: a snapshot failure must never block saving a config.
    Returns the snapshot path on success, else ``None``.
    """
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"xray-{stamp}-{time.time_ns()}.json"
        path = os.path.join(HISTORY_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
        _prune()
        return path
    except Exception:
        logger.warning("Failed to snapshot Xray config to history", exc_info=True)
        return None


def list_snapshots() -> List[dict]:
    """Return snapshots newest-first with ``name``, ``size`` and ``mtime``."""
    try:
        entries = []
        for fname in os.listdir(HISTORY_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(HISTORY_DIR, fname)
            try:
                st = os.stat(fpath)
            except OSError:
                continue
            entries.append({"name": fname, "size": st.st_size, "mtime": int(st.st_mtime)})
        entries.sort(key=lambda e: e["name"], reverse=True)
        return entries
    except OSError:
        return []


def read_snapshot(name: str) -> Optional[dict]:
    """Load and parse a snapshot by name. Rejects path traversal."""
    if not name or "/" in name or "\\" in name or not name.endswith(".json"):
        return None
    path = os.path.join(HISTORY_DIR, name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        logger.warning("Failed to read Xray config snapshot %s", name, exc_info=True)
        return None


def restore_config_file(raw: str, path: Optional[str] = None) -> bool:
    """Write ``raw`` back to the master config file (auto-rollback helper).

    Best-effort: returns ``True`` when the file was written successfully.
    """
    target = path or XRAY_JSON
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(raw)
        return True
    except OSError:
        logger.warning("Failed to restore Xray config file to %s", target, exc_info=True)
        return False


def _prune() -> None:
    names = [e["name"] for e in list_snapshots()]
    for stale in names[MAX_SNAPSHOTS:]:
        try:
            os.remove(os.path.join(HISTORY_DIR, stale))
        except OSError:
            pass
