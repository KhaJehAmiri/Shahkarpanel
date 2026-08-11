from concurrent.futures import ThreadPoolExecutor
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
