"""Process role: API vs control-plane worker vs single-process (all).

The node agent keeps a single RPyC session. API and worker must not both
dial nodes. Interval jobs (usage, health, Finalmask) must not run inside
the HTTP worker — that is what froze the dashboard.

``SHAHKAR_ROLE``:

* ``all`` (default) — current one-process panel (dev / old compose)
* ``api`` — FastAPI only; delegates node RPC via the wake channel
* ``worker`` — scheduler, local Xray, node sessions; no HTTP
"""
from __future__ import annotations

import os

_VALID = frozenset({"all", "api", "worker"})


def role() -> str:
    raw = (os.environ.get("SHAHKAR_ROLE") or "all").strip().lower()
    return raw if raw in _VALID else "all"


def owns_control_plane() -> bool:
    """Local Xray, node RPyC, scheduler jobs, presence QueryStats."""
    return role() in ("all", "worker")


def owns_http() -> bool:
    return role() in ("all", "api")


def delegate_to_worker(kind: str, payload: str = "") -> bool:
    """If this process is API-only, enqueue work for the worker and return True.

    Callers: ``if delegate_to_worker(\"user_change\"): return``.
    """
    if owns_control_plane():
        return False
    try:
        from app.sync.wake import notify_worker

        notify_worker(kind, payload)
    except Exception:
        import logging

        logging.getLogger("uvicorn.error").exception(
            "failed to wake worker kind=%s payload=%s", kind, payload
        )
    return True
