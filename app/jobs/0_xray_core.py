import time
import traceback

from app import app, logger, scheduler, xray
from app.db import GetDB, crud
from app.models.node import NodeStatus
from config import JOB_CORE_HEALTH_CHECK_INTERVAL, JOB_CORE_USER_RECONCILE_INTERVAL
from xray_api import exc as xray_exc

_NODE_RESTART_COOLDOWN_SEC = 60
_node_restart_after: dict[int, float] = {}


def _record_node_health(node_id: int, latency_ms: float):
    try:
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode:
                crud.update_node_health(db, dbnode, latency_ms)
    except Exception:
        pass


def _stdin_xray_pids() -> list[int]:
    import subprocess
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "^/usr/local/bin/xray run -config stdin:"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    pids: list[int] = []
    for line in out.strip().splitlines():
        if line.strip().isdigit():
            pids.append(int(line.strip()))
    return pids


def core_health_check():
    if xray.core.restarting:
        return

    config = None
    now = time.time()

    # main core — recover from crash/duplicate processes without dropping live sessions
    pids = _stdin_xray_pids()
    keep_pid = xray.core.process.pid if xray.core.process else None
    panel_running = xray.core.started and keep_pid in pids

    if panel_running and len(pids) > 1:
        logger.warning("Detected %s Xray stdin processes; killing extras", len(pids))
        xray.core._kill_stale_stdin_xray(keep_pid=keep_pid)
    elif not panel_running:
        if len(pids) > 0 and keep_pid is None:
            # Orphan from a crashed/replaced panel — clean once, then start tracked.
            logger.warning("Untracked Xray stdin process(es) %s; reconciling once", pids)
            xray.core._kill_stale_stdin_xray(keep_pid=None)
            pids = []
        if len(pids) == 0:
            poll = xray.core.process.poll() if xray.core.process else None
            logger.debug(
                "Health check restarting main core (started=%s keep_pid=%s poll=%s stdin_pids=%s)",
                xray.core.started,
                keep_pid,
                poll,
                pids,
            )
            if not config:
                config = xray.config.include_db_users()
            xray.core.restart(config)

    # nodes' core
    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            try:
                assert node.started
                probe_start = time.time()
                node.api.get_sys_stats(timeout=2)
                latency_ms = (time.time() - probe_start) * 1000
                _record_node_health(node_id, latency_ms)
            except (ConnectionError, xray_exc.XrayError, AssertionError):
                if now < _node_restart_after.get(node_id, 0):
                    continue
                _node_restart_after[node_id] = now + _NODE_RESTART_COOLDOWN_SEC
                if not config:
                    config = xray.config.include_db_users()
                xray.operations.restart_node(node_id, config)

        if not node.connected:
            if now < _node_restart_after.get(node_id, 0):
                continue
            if not config:
                config = xray.config.include_db_users()
            xray.operations.connect_node(node_id, config)


@app.on_event("startup")
def start_core():
    logger.info("Generating Xray core config")

    start_time = time.time()
    config = xray.config.include_db_users()
    logger.info(f"Xray core config generated in {(time.time() - start_time):.2f} seconds")

    # main core — drop orphans from a prior panel instance before binding API.
    xray.core._kill_stale_stdin_xray(keep_pid=None)

    logger.info("Starting main Xray core")
    try:
        xray.core.start(config)
    except Exception:
        traceback.print_exc()

    # nodes' core
    logger.info("Starting nodes Xray core")
    with GetDB() as db:
        dbnodes = crud.get_nodes(db=db, enabled=True)
        node_ids = [dbnode.id for dbnode in dbnodes]
        for dbnode in dbnodes:
            crud.update_node_status(db, dbnode, NodeStatus.connecting)

    for node_id in node_ids:
        xray.operations.connect_node(node_id, config)

    from app.ha import run_if_leader
    scheduler.add_job(
        run_if_leader(core_health_check),
        'interval',
        seconds=JOB_CORE_HEALTH_CHECK_INTERVAL,
        coalesce=True,
        max_instances=1,
    )

    # Safety net: re-apply the DB → live-core user diff so an active user can
    # never stay missing after a transient API hiccup or restart race.
    from app.xray.serving import reconcile_core_users
    scheduler.add_job(
        run_if_leader(reconcile_core_users),
        'interval',
        seconds=JOB_CORE_USER_RECONCILE_INTERVAL,
        coalesce=True,
        max_instances=1,
    )


@app.on_event("shutdown")
def app_shutdown():
    logger.info("Stopping main Xray core")
    xray.core.stop()

    logger.info("Stopping nodes Xray core")
    for node in list(xray.nodes.values()):
        try:
            node.disconnect()
        except Exception:
            pass
