"""In-memory registry for background 3x-ui migration jobs.

A large panel import (thousands of clients) takes long enough to blow past
reverse-proxy / client HTTP timeouts, which left imports looking "stuck" or
half-applied. The run endpoint now hands the work to a background thread and
returns a job id immediately; the UI polls :func:`get` for live progress and
the final per-panel results. State is process-local (single-node panel), which
is sufficient — a job that dies with the process is simply re-runnable and the
import itself is idempotent.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MigrationJob:
    id: str
    state: str = "running"  # running | done | error
    total: int = 0
    processed: int = 0
    results: list = field(default_factory=list)
    uuid_collisions: Optional[dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "state": self.state,
            "total": self.total,
            "processed": self.processed,
            "results": self.results,
            "uuid_collisions": self.uuid_collisions,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }


_lock = threading.Lock()
_jobs: dict[str, MigrationJob] = {}
_active_id: Optional[str] = None
_MAX_KEEP_SEC = 3600  # drop finished jobs after an hour


def _prune_locked() -> None:
    now = time.time()
    stale = [
        jid
        for jid, job in _jobs.items()
        if job.finished_at is not None and (now - job.finished_at) > _MAX_KEEP_SEC
    ]
    for jid in stale:
        _jobs.pop(jid, None)


def active_job() -> Optional[MigrationJob]:
    """The currently running job, if any (only one runs at a time)."""
    with _lock:
        if _active_id is None:
            return None
        return _jobs.get(_active_id)


def create() -> MigrationJob:
    """Register a new running job and mark it active. Caller must run it."""
    global _active_id
    with _lock:
        _prune_locked()
        job = MigrationJob(id=uuid.uuid4().hex)
        _jobs[job.id] = job
        _active_id = job.id
        return job


def get(job_id: str) -> Optional[MigrationJob]:
    with _lock:
        return _jobs.get(job_id)


def bump_progress(job_id: str, processed_delta: int = 0, total_delta: int = 0) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.processed += int(processed_delta or 0)
        job.total += int(total_delta or 0)
        job.updated_at = time.time()


def finish(
    job_id: str,
    *,
    state: str,
    results: Optional[list] = None,
    uuid_collisions: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    global _active_id
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.state = state
            if results is not None:
                job.results = results
            job.uuid_collisions = uuid_collisions
            job.error = error
            job.finished_at = time.time()
            job.updated_at = job.finished_at
        if _active_id == job_id:
            _active_id = None
