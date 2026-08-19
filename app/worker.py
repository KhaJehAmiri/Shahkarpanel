"""Control-plane worker: scheduler, local Xray, node RPyC. No HTTP bind."""
from __future__ import annotations

import logging
import os
import signal
import sys
import time

# Must be set before importing app so job/start_core guards see the role.
os.environ.setdefault("SHAHKAR_ROLE", "worker")

from app import logger, scheduler  # noqa: E402
from app.ha import start as ha_start  # noqa: E402
from app.ha import stop as ha_stop  # noqa: E402
from app.presence import start_presence_worker, stop_presence_worker  # noqa: E402
from app.runtime_role import owns_control_plane, role  # noqa: E402
from app.sync.wake import start_wake_listener, stop_wake_listener, write_heartbeat  # noqa: E402
from app.utils.logging import setup_structured_logging  # noqa: E402
from config import LOG_JSON  # noqa: E402

_stop = False


def _wait_for_db(timeout_sec: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            from sqlalchemy import text

            from app.db import GetDB

            with GetDB() as db:
                db.execute(text("SELECT 1"))
            return
        except Exception:
            time.sleep(1.5)
    raise RuntimeError("worker: database not reachable")


def _handle_stop(signum, _frame) -> None:
    global _stop
    logger.info("worker received signal %s", signum)
    _stop = True


def main() -> int:
    if not owns_control_plane():
        logger.error("worker started with SHAHKAR_ROLE=%s (need worker|all)", role())
        return 2
    setup_structured_logging(LOG_JSON)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logger.info("Shahkar worker starting role=%s pid=%s", role(), os.getpid())
    _wait_for_db()
    write_heartbeat()
    try:
        from app.utils.system import start_overview_live_ticks

        start_overview_live_ticks()
    except Exception:
        logger.exception("overview live ticks failed to start")
    ha_start()
    start_presence_worker()
    from app.jobs.core_boot import start_core

    start_core()
    scheduler.start()
    start_wake_listener()
    try:
        from app.sync.live import load_census, publish_tick

        load_census(force=True)
        publish_tick()
    except Exception:
        logger.exception("initial live snapshot failed")
    try:
        from app.telegram import start_bot_polling

        start_bot_polling()
    except Exception:
        logger.exception("telegram polling on worker failed")
    try:
        from app.sync.outbox import drain

        drain()
    except Exception:
        logger.exception("initial outbox drain failed")
    write_heartbeat()
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    while not _stop:
        write_heartbeat()
        time.sleep(2.0)
    logger.info("Shahkar worker shutting down")
    stop_wake_listener()
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    stop_presence_worker()
    ha_stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
