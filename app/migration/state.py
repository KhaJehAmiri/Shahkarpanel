"""Migration-in-progress guard for background jobs and Xray sync."""
from __future__ import annotations

import threading
from contextlib import contextmanager

_lock = threading.Lock()
_depth = 0


def migration_active() -> bool:
    with _lock:
        return _depth > 0


@contextmanager
def migration_context():
    global _depth
    with _lock:
        _depth += 1
    try:
        yield
    finally:
        with _lock:
            _depth -= 1
