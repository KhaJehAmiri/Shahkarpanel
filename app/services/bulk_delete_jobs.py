"""In-memory registry for background bulk-delete jobs.

Deleting thousands of users synchronously inside the HTTP request outlives
reverse-proxy timeouts (nginx returns 499 / Cloudflare 524), so the UI shows
"Server error" even when the delete eventually succeeds. The run endpoint
hands the work to a background thread and returns a job id immediately; the
UI polls :func:`get` for live progress. Process-local state is enough for a
single-node panel; a crashed job is simply re-runnable.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BulkDeleteJob:
    id: str
    state: str = "running"  # running | done | error
    total: int = 0
    processed: int = 0
    deleted: int = 0
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
            "deleted": self.deleted,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }


_lock = threading.Lock()
_jobs: dict[str, BulkDeleteJob] = {}
_active_id: Optional[str] = None
_MAX_KEEP_SEC = 3600


def _prune_locked() -> None:
    now = time.time()
    stale = [
        jid
        for jid, job in _jobs.items()
        if job.finished_at is not None and (now - job.finished_at) > _MAX_KEEP_SEC
    ]
    for jid in stale:
        _jobs.pop(jid, None)


def active_job() -> Optional[BulkDeleteJob]:
    with _lock:
        if _active_id is None:
            return None
        return _jobs.get(_active_id)


def create(*, total: int = 0) -> BulkDeleteJob:
    global _active_id
    with _lock:
        _prune_locked()
        job = BulkDeleteJob(id=uuid.uuid4().hex, total=int(total or 0))
        _jobs[job.id] = job
        _active_id = job.id
        return job


def get(job_id: str) -> Optional[BulkDeleteJob]:
    with _lock:
        return _jobs.get(job_id)


def bump(job_id: str, *, processed_delta: int = 0, deleted_delta: int = 0, total: Optional[int] = None) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.processed += int(processed_delta or 0)
        job.deleted += int(deleted_delta or 0)
        if total is not None:
            job.total = int(total)
        job.updated_at = time.time()


def finish(
    job_id: str,
    *,
    state: str,
    deleted: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    global _active_id
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.state = state
            if deleted is not None:
                job.deleted = int(deleted)
                job.processed = max(job.processed, job.deleted)
            job.error = error
            job.finished_at = time.time()
            job.updated_at = job.finished_at
        if _active_id == job_id:
            _active_id = None
