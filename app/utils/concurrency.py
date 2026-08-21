from concurrent.futures import ThreadPoolExecutor, wait
from threading import Thread, Semaphore
import os

import anyio
from fastapi import BackgroundTasks


# Cap concurrent node AlterInbound RPCs. Digicdn relays sit behind SSH control
# tunnels; unbounded remove/add threads each wait for gRPC Deadline and starve
# the single uvicorn worker (dashboard "loads forever").
_NODE_ALTER_CONCURRENCY = max(2, int(os.environ.get("NODE_ALTER_RPC_CONCURRENCY", "8")))
_NODE_ALTER_SEM = Semaphore(_NODE_ALTER_CONCURRENCY)
_NODE_ALTER_TIMEOUT = float(os.environ.get("NODE_ALTER_RPC_TIMEOUT", "2.5"))
# Bounded pool — ``@threaded_function`` + semaphore still spawned one OS thread
# per call; under sync storms that reached 5k+ threads and froze the panel.
_NODE_ALTER_POOL = ThreadPoolExecutor(
    max_workers=_NODE_ALTER_CONCURRENCY,
    thread_name_prefix="node-alter",
)

# Shared fleet-RPC pool. Usage / presence / bandwidth used to construct a
# fresh ThreadPoolExecutor every tick and ``shutdown(wait=False)``. Hung node
# RPCs then leaked OS threads until the single uvicorn worker froze and only
# a Docker restart recovered it.
_NODE_RPC_WORKERS = max(4, int(os.environ.get("NODE_RPC_POOL_SIZE", "16")))
_NODE_RPC_POOL = ThreadPoolExecutor(
    max_workers=_NODE_RPC_WORKERS,
    thread_name_prefix="node-rpc",
)
_NODE_RPC_QUEUE_CAP = Semaphore(_NODE_RPC_WORKERS * 2)


def map_rpc(func, items: dict, timeout: float, default=None) -> dict:
    """Run ``func(key, value)`` for each item under one wall-clock timeout.

    Submits onto the process-wide pool. If the pool is saturated, the key is
    skipped (same as a timeout) instead of queueing unbounded work.

    Important: wait once for the whole batch. A per-future ``result(timeout)``
    loop used to stack (N × timeout) when several nodes hung — with 14 nodes
    and timeout=12 that pinned ``record_user_usages`` for minutes
    (``max_instances=1`` → every 5s tick skipped).
    """
    if not items:
        return {}
    futures = {}
    for key, value in items.items():
        if not _NODE_RPC_QUEUE_CAP.acquire(blocking=False):
            continue

        def _run(fn=func, k=key, v=value):
            try:
                return fn(k, v)
            finally:
                _NODE_RPC_QUEUE_CAP.release()

        try:
            futures[key] = _NODE_RPC_POOL.submit(_run)
        except RuntimeError:
            _NODE_RPC_QUEUE_CAP.release()
    out = {}
    if not futures:
        return out
    wait(list(futures.values()), timeout=max(0.1, float(timeout)))
    for key, fut in futures.items():
        if fut.done():
            try:
                out[key] = fut.result(timeout=0)
            except Exception:
                out[key] = default
        else:
            out[key] = default
    return out


def threaded_function(func):
    def wrapper(*args, **kwargs):
        thread = Thread(target=func, args=args, daemon=True, kwargs=kwargs)
        thread.start()
    return wrapper


def node_alter_threaded(func):
    """Queue AlterInbound work on the bounded pool (no per-call Thread)."""

    def wrapper(*args, **kwargs):
        try:
            _NODE_ALTER_POOL.submit(func, *args, **kwargs)
        except RuntimeError:
            # Interpreter / pool shutdown
            pass

    return wrapper


def node_alter_rpc_guard(func):
    """Run a node Proxyman RPC under the concurrency semaphore.

    Prefer ``@node_alter_threaded`` for new call sites — this guard alone does
    not stop ``@threaded_function`` from creating unbounded threads.
    """

    def wrapper(*args, **kwargs):
        acquired = _NODE_ALTER_SEM.acquire(timeout=0.2)
        if not acquired:
            # Prefer dropping a transient sync over pinning hundreds of threads.
            return
        try:
            return func(*args, **kwargs)
        finally:
            _NODE_ALTER_SEM.release()

    return wrapper


class GetBG:
    """
    context manager for fastapi.BackgroundTasks
    """

    def __init__(self):
        self.bg = BackgroundTasks()

    def __enter__(self):
        return self.bg

    def __exit__(self, exc_type, exc_value, traceback):
        Thread(target=anyio.run, args=(self.bg,), daemon=True).start()

    async def __aenter__(self):
        return self.bg

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.bg()
