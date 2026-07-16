import time
import traceback

from app import app, logger, scheduler, xray
from app.db import GetDB, crud
from app.models.node import NodeStatus
from config import (
    CORE_HEALTH_API_FAILURE_THRESHOLD,
    CORE_HEALTH_API_RETRIES,
    CORE_HEALTH_API_TIMEOUT,
    JOB_AWG_FLUSH_STALE_PEERS,
    JOB_CORE_HEALTH_CHECK_INTERVAL,
    JOB_CORE_USER_RECONCILE_INTERVAL,
)
from xray_api import exc as xray_exc

_NODE_RESTART_COOLDOWN_SEC = 60
_node_restart_after: dict[int, float] = {}
_WG_RESYNC_COOLDOWN_SEC = 300
_wg_resync_after: dict[int, float] = {}
_WG_FLUSH_COOLDOWN_SEC = 4
_wg_flush_after: dict[int, float] = {}
_BIND_FAILURE_BACKOFF_SEC = 120.0
_bind_failure_backoff_until: float = 0.0
_last_bind_failure_key: tuple[int | None, str | None] | None = None

# Consecutive health ticks where the (alive) main core's gRPC API did not answer.
# Reset to 0 on any successful probe; a restart only fires once it reaches
# CORE_HEALTH_API_FAILURE_THRESHOLD so a momentary blip never drops everyone.
_api_unreachable_streak = 0


def _probe_main_core_api() -> bool:
    """True if the main core's stats API answers within a few in-tick retries.

    The process is already confirmed alive by the caller; this only distinguishes
    a genuinely wedged core from a transient gRPC hiccup. We retry a couple of
    times with a short backoff before declaring the whole tick a failure.
    """
    attempts = max(1, CORE_HEALTH_API_RETRIES + 1)
    for attempt in range(attempts):
        try:
            xray.api.get_sys_stats(timeout=CORE_HEALTH_API_TIMEOUT)
            return True
        except Exception:
            if attempt < attempts - 1:
                time.sleep(0.5)
    return False


def _health_check_config():
    """Prefer the last booted config during bind-failure recovery — rebuilding
    from the DB on every tick is expensive and races with in-flight migrations."""
    last = getattr(xray.core, "last_config", None)
    if last is not None and xray.core.startup_error and not xray.core.started:
        return last
    return xray.config.include_db_users()


def _arm_bind_failure_backoff(now: float) -> None:
    global _bind_failure_backoff_until, _last_bind_failure_key
    key = (getattr(xray.core, "failed_port", None), getattr(xray.core, "failed_inbound_tag", None))
    if key == _last_bind_failure_key and key != (None, None):
        _bind_failure_backoff_until = now + _BIND_FAILURE_BACKOFF_SEC
    else:
        _last_bind_failure_key = key
        _bind_failure_backoff_until = now + 30.0


def _clear_bind_failure_backoff() -> None:
    global _bind_failure_backoff_until, _last_bind_failure_key
    _bind_failure_backoff_until = 0.0
    _last_bind_failure_key = None


def _node_probe_meta(node_id: int) -> tuple[str | None, str | None]:
    """Single DB round-trip returning ``(core_kind, wg_probe_interface)``.

    Previously ``_node_core_kind`` and ``_wireguard_probe_interface`` each ran
    their own ``get_node_by_id`` query, and callers such as
    ``_probe_wireguard_node``/``_maybe_reconcile_awg_endpoints`` invoked both —
    doubling (or worse, per health-check tick) the DB load for N nodes
    (AUDIT_FINDINGS.md M4). Fetch the node once and derive both values from it.
    """
    try:
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode is None:
                return None, None
            core_kind = dbnode.core_kind
            cfg = dbnode.wireguard
            if cfg is None:
                return core_kind, None
            from app.wireguard.sync import amneziawg_enabled

            iface = cfg.awg_interface if (amneziawg_enabled(cfg) and cfg.awg_interface) else cfg.interface
            return core_kind, iface
    except Exception:
        return None, None


def _node_core_kind(node_id: int) -> str | None:
    """Back-compat single-value accessor — prefer ``_node_probe_meta`` when
    both the core kind and the WG interface are needed together."""
    return _node_probe_meta(node_id)[0]


def _wireguard_probe_interface(node_id: int) -> str | None:
    """Return the primary WG interface to probe on a node, or ``None``."""
    return _node_probe_meta(node_id)[1]


def _probe_wireguard_node(
    node_id: int, node, *, meta: tuple[str | None, str | None] | None = None
) -> float:
    """Health probe for WireGuard nodes: RPyC channel + WG or tunnel relay.

    Relay nodes that delegate the public UDP port to Xray keep native ``wg0``
    down on purpose; probing ``wg_transfer`` there would always fail and
    trigger needless ``connect_node`` restarts that drop live clients.

    ``meta`` lets the caller (``core_health_check``) pass an already-fetched
    ``(core_kind, iface)`` pair for this tick instead of re-querying the DB.
    """
    from app.models.node import CoreKind
    from app.tunnel.relay import node_delegates_wireguard_to_tunnel, relay_tunnel_xray_ready

    core_kind, iface = meta if meta is not None else _node_probe_meta(node_id)
    if core_kind != CoreKind.wireguard.value:
        raise AssertionError("not a wireguard node")
    probe_start = time.time()
    with GetDB() as db:
        delegates_tunnel = node_delegates_wireguard_to_tunnel(db, node_id)
        if delegates_tunnel:
            if not relay_tunnel_xray_ready(node, db=db, node_id=node_id):
                raise ConnectionError("tunnel relay Xray is not ready")
            return (time.time() - probe_start) * 1000
    if not node.connected:
        raise ConnectionError("node RPyC channel is down")
    if iface:
        from app.wireguard.transport import client_for_node

        client = client_for_node(node)
        if client is None:
            raise ConnectionError("no WireGuard transport on node")
        client.transfer(iface)
    return (time.time() - probe_start) * 1000


_WG_BAD_EP_COOLDOWN_SEC = 10
_WG_BAD_EP_ERROR_BACKOFF_SEC = 2
_wg_bad_ep_after: dict[int, float] = {}


def _maybe_reconcile_awg_endpoints(
    node_id: int, node, now: float, *, meta: tuple[str | None, str | None] | None = None
) -> None:
    """Clear dead/stale learned endpoints (handshake=0, bad host, expired).

    The cooldown is only armed for the full interval *after* the RPyC call
    actually completes (success or a real, observed failure). If the call
    never got a chance to run — e.g. the transport was unavailable — a short
    backoff is used instead so a transient hiccup doesn't leave stale/dead
    endpoints unreconciled for a full ``_WG_BAD_EP_COOLDOWN_SEC`` while having
    accomplished nothing (AUDIT_FINDINGS.md M5).
    """
    if now < _wg_bad_ep_after.get(node_id, 0):
        return
    core_kind, iface = meta if meta is not None else _node_probe_meta(node_id)
    if core_kind != "wireguard":
        return
    if not iface:
        return
    try:
        from app.wireguard.transport import client_for_node

        client = client_for_node(node)
        if client is not None and hasattr(client, "reconcile_awg_endpoints"):
            client.reconcile_awg_endpoints(iface)
        elif client is not None and hasattr(client, "flush_bad_endpoints"):
            client.flush_bad_endpoints(iface)
        _wg_bad_ep_after[node_id] = now + _WG_BAD_EP_COOLDOWN_SEC
    except Exception as exc:
        _wg_bad_ep_after[node_id] = now + _WG_BAD_EP_ERROR_BACKOFF_SEC
        logger.debug("AWG endpoint reconcile for node %s skipped: %s", node_id, exc)


def _maybe_flush_awg_peers(
    node_id: int, node, now: float, *, meta: tuple[str | None, str | None] | None = None
) -> None:
    """Clear idle AWG peer endpoints so mobile clients can reconnect."""
    if now < _wg_flush_after.get(node_id, 0):
        return
    _wg_flush_after[node_id] = now + _WG_FLUSH_COOLDOWN_SEC
    core_kind, iface = meta if meta is not None else _node_probe_meta(node_id)
    if core_kind != "wireguard":
        return
    if not iface:
        return
    try:
        from app.wireguard.transport import client_for_node

        client = client_for_node(node)
        if client is not None and hasattr(client, "flush_stale_peers"):
            client.flush_stale_peers(iface, idle_sec=11, traffic_only=True)
    except Exception as exc:
        logger.debug("AWG peer flush for node %s skipped: %s", node_id, exc)


def _maybe_resync_wireguard(node_id: int, node, now: float) -> None:
    if now < _wg_resync_after.get(node_id, 0):
        return
    _wg_resync_after[node_id] = now + _WG_RESYNC_COOLDOWN_SEC
    try:
        from app.xray.operations import _sync_wireguard_node

        _sync_wireguard_node(node_id, node)
    except Exception as exc:
        logger.debug("Periodic WireGuard resync for node %s skipped: %s", node_id, exc)


def _record_node_health(node_id: int, latency_ms: float):
    try:
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode:
                crud.update_node_health(db, dbnode, latency_ms)
    except Exception:
        pass


def _stdin_xray_pids() -> list[int]:
    from config import XRAY_EXECUTABLE_PATH
    from app.xray.core import find_stdin_xray_pids

    return find_stdin_xray_pids(XRAY_EXECUTABLE_PATH)


def core_health_check():
    if xray.core.restarting:
        return

    try:
        from app.migration.state import migration_active
    except ImportError:
        migration_active = lambda: False  # noqa: E731

    if migration_active():
        return

    config = None
    now = time.time()

    if xray.core.in_health_restart_cooldown(now):
        return

    if xray.core.startup_error and not xray.core.started and now < _bind_failure_backoff_until:
        return

    # main core — recover from crash/duplicate processes without dropping live sessions
    pids = _stdin_xray_pids()
    keep_pid = xray.core.process.pid if xray.core.process else None
    panel_running = xray.core.started and keep_pid in pids

    if panel_running and len(pids) > 1:
        logger.warning("Detected %s Xray stdin processes; killing extras", len(pids))
        xray.core._kill_stale_stdin_xray(keep_pid=keep_pid)
        _clear_bind_failure_backoff()
    elif panel_running:
        global _api_unreachable_streak
        grace_sec = 15
        started_at = getattr(xray.core, "started_at", None)
        if started_at is not None and (now - started_at) < grace_sec:
            return
        if _probe_main_core_api():
            _api_unreachable_streak = 0
            _clear_bind_failure_backoff()
        else:
            _api_unreachable_streak += 1
            if _api_unreachable_streak < CORE_HEALTH_API_FAILURE_THRESHOLD:
                # Process is alive; a single (or few) missed probe is almost
                # always a transient blip. Wait for a sustained streak before
                # restarting so we never drop every user over a momentary spike.
                logger.warning(
                    "Xray process alive but API probe failed (%d/%d consecutive ticks); "
                    "deferring restart",
                    _api_unreachable_streak,
                    CORE_HEALTH_API_FAILURE_THRESHOLD,
                )
                return
            logger.warning(
                "Xray process alive but API unreachable for %d consecutive ticks; restarting core",
                _api_unreachable_streak,
            )
            _api_unreachable_streak = 0
            if not config:
                config = _health_check_config()
            xray.core.restart(config)
    elif not panel_running:
        if not config:
            config = _health_check_config()
        if xray.core.startup_error and not xray.core.started:
            logger.warning(
                "Xray bind/startup failure (%s); reclaiming listen ports",
                xray.core.startup_error,
            )
            try:
                xray.core.restart(config)
            except Exception:
                logger.exception("Xray restart after startup failure failed")
            else:
                if not xray.core.started:
                    _arm_bind_failure_backoff(now)
            return
        if len(pids) > 0 and (keep_pid is None or keep_pid not in pids):
            # Orphan from a crashed/replaced panel — reclaim ports then start tracked.
            logger.warning("Untracked Xray stdin process(es) %s; reclaiming and restarting", pids)
            try:
                xray.core.restart(config)
            except Exception:
                logger.exception("Xray restart after orphan reclaim failed")
            return
        if len(pids) == 0:
            poll = xray.core.process.poll() if xray.core.process else None
            logger.warning(
                "Health check restarting main core (started=%s keep_pid=%s poll=%s stdin_pids=%s)",
                xray.core.started,
                keep_pid,
                poll,
                pids,
            )
            if not config:
                config = _health_check_config()
            try:
                xray.core.restart(config)
            except Exception:
                logger.exception("Xray health-check restart failed")

    # nodes' core
    from app.models.node import CoreKind

    for node_id, node in list(xray.nodes.items()):
        # One fetch per node per tick, reused below — used to be up to 6
        # separate `get_node_by_id` queries per WireGuard node per tick
        # (AUDIT_FINDINGS.md M4).
        node_meta = _node_probe_meta(node_id)
        is_wg_node = node_meta[0] == CoreKind.wireguard.value
        if node.connected:
            try:
                if is_wg_node:
                    latency_ms = _probe_wireguard_node(node_id, node, meta=node_meta)
                    _record_node_health(node_id, latency_ms)
                    _maybe_reconcile_awg_endpoints(node_id, node, now, meta=node_meta)
                    if JOB_AWG_FLUSH_STALE_PEERS:
                        _maybe_flush_awg_peers(node_id, node, now, meta=node_meta)
                    _maybe_resync_wireguard(node_id, node, now)
                else:
                    assert node.started
                    probe_start = time.time()
                    node.api.get_sys_stats(timeout=2)
                    latency_ms = (time.time() - probe_start) * 1000
                    _record_node_health(node_id, latency_ms)
            except (ConnectionError, xray_exc.XrayError, AssertionError, TimeoutError, EOFError):
                if now < _node_restart_after.get(node_id, 0):
                    continue
                if is_wg_node:
                    from app.tunnel.relay import (
                        node_delegates_wireguard_to_tunnel,
                        relay_tunnel_xray_ready,
                    )

                    with GetDB() as db:
                        delegates_tunnel = node_delegates_wireguard_to_tunnel(
                            db, node_id
                        )
                        tunnel_ready = delegates_tunnel and relay_tunnel_xray_ready(
                            node, db=db, node_id=node_id
                        )
                    if tunnel_ready:
                        _record_node_health(node_id, 0.0)
                        continue
                _node_restart_after[node_id] = now + _NODE_RESTART_COOLDOWN_SEC
                if not config:
                    config = _health_check_config()
                if is_wg_node:
                    xray.operations.connect_node(node_id, config)
                else:
                    xray.operations.restart_node(node_id, config)

        if not node.connected:
            if now < _node_restart_after.get(node_id, 0):
                continue
            # Tunnel-delegated relays can keep serving WG while the panel-side
            # RPyC session is briefly unhealthy — do not restart Xray for that.
            if is_wg_node:
                from app.tunnel.relay import node_delegates_wireguard_to_tunnel, relay_tunnel_xray_ready

                with GetDB() as db:
                    delegates_tunnel = node_delegates_wireguard_to_tunnel(db, node_id)
                    tunnel_ready = delegates_tunnel and relay_tunnel_xray_ready(
                        node, db=db, node_id=node_id
                    )
                if tunnel_ready:
                    _record_node_health(node_id, 0.0)
                    continue
            try:
                from app.control_tunnel import heal_tunnels

                heal_tunnels()
            except Exception:
                pass
            if not config:
                config = _health_check_config()
            xray.operations.connect_node(node_id, config)


@app.on_event("startup")
def start_core():
    """Start main Xray (with users) then connect nodes — must finish before relying on traffic.

    A previous experiment deferred this to a background thread so HTTP listened
    sooner; that raced with orphan processes and left the core unmarked
    (``core.started=False``) while an empty-config Xray kept the ports —
    every client timed out. Keep boot synchronous; nginx already shows a
    restarting page during the brief downtime.
    """
    if getattr(app.state, "_xray_core_boot_started", False):
        return
    app.state._xray_core_boot_started = True

    logger.info("Generating Xray core config")
    start_time = time.time()
    config = xray.config.include_db_users()
    logger.info(
        "Xray core config generated in %.2f seconds",
        time.time() - start_time,
    )

    logger.info("Starting main Xray core")
    try:
        xray.core.restart(config, force=True)
    except Exception:
        logger.exception("Failed to start main Xray core")

    try:
        from app.services.panel_warp_egress import sync_panel_warp_egress

        with GetDB() as db:
            sync_panel_warp_egress(db)
    except Exception:
        logger.exception("Panel WARP egress sync on startup failed")

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
        "interval",
        seconds=JOB_CORE_HEALTH_CHECK_INTERVAL,
        coalesce=True,
        max_instances=1,
        id="core_health_check",
        replace_existing=True,
    )

    from app.xray.serving import reconcile_core_users

    scheduler.add_job(
        run_if_leader(reconcile_core_users),
        "interval",
        seconds=JOB_CORE_USER_RECONCILE_INTERVAL,
        coalesce=True,
        max_instances=1,
        id="core_user_reconcile",
        replace_existing=True,
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
