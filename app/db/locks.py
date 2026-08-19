"""Cross-process exclusive locks.

In-process ``threading.Lock`` is not enough once the API has more than one
uvicorn worker. Postgres ``pg_advisory_xact_lock`` is held until COMMIT/ROLLBACK
of the current session. SQLite (tests) falls back to a thread lock.
"""
from __future__ import annotations

import threading
import zlib
from contextlib import contextmanager

from sqlalchemy import text

_thread_locks: dict[str, threading.Lock] = {}
_thread_guard = threading.Lock()


def _thread_lock(name: str) -> threading.Lock:
    with _thread_guard:
        lock = _thread_locks.get(name)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[name] = lock
        return lock


@contextmanager
def exclusive(db, name: str):
    """Serialize work named ``name`` across API workers and the control plane."""
    from app.db.base import IS_POSTGRESQL

    if IS_POSTGRESQL:
        key = zlib.crc32(name.encode("utf-8")) & 0x7FFFFFFF
        db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=int(key)))
        yield
        return
    with _thread_lock(name):
        yield
