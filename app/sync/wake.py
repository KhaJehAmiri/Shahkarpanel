"""Wake the control-plane worker from the API process.

The node agent accepts one RPyC session. User create on the API therefore
cannot dial nodes; it persists DB + dirty slots and pushes a wake so the
worker applies immediately instead of waiting for the next interval job.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("uvicorn.error")

WAKE_KEY = "shahkar:worker:wake"
HEARTBEAT_KEY = "shahkar:worker:heartbeat"
METRICS_BW_KEY = "shahkar:metrics:bandwidth"
_DATA_DIR = Path(os.environ.get("SHAHKAR_DATA_DIR", "/var/lib/shahkar"))
_WAKE_FILE = Path(os.environ.get("SHAHKAR_WAKE_FILE", str(_DATA_DIR / "worker.wake")))
_HEARTBEAT_FILE = Path(
    os.environ.get("SHAHKAR_WORKER_HEARTBEAT", str(_DATA_DIR / "worker.heartbeat"))
)

_stop = threading.Event()
_listener: Optional[threading.Thread] = None


def _redis():
    from config import REDIS_URL

    if not REDIS_URL:
        return None
    try:
        import redis

        return redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=2.5,
        )
    except Exception:
        return None


def apply_fleet_resync() -> None:
    """Align main core + connected nodes + WG + sing-box with the DB.

    Worker-only. HTTP must call ``request_fleet_resync`` so the API process
    never walks ``xray.nodes`` (empty on the split API role).
    """
    try:
        from app.xray.serving import schedule_core_sync

        schedule_core_sync(delay=0.2)
    except Exception:
        logger.exception("fleet resync core_sync failed")
    try:
        from app.xray.operations import push_connected_nodes_config_sync

        push_connected_nodes_config_sync()
    except Exception:
        logger.exception("fleet resync node push failed")
    try:
        from app.xray.operations import _sync_wireguard

        _sync_wireguard()
    except Exception:
        logger.exception("fleet resync wireguard failed")
    try:
        from app.singbox.operations import sync_user_change as singbox_sync

        singbox_sync()
    except Exception:
        logger.exception("fleet resync sing-box failed")


def request_fleet_resync() -> None:
    """Run fleet resync here if we own the control plane, else wake the worker."""
    from app.runtime_role import owns_control_plane

    if not owns_control_plane():
        notify_worker("resync_fleet")
        return
    apply_fleet_resync()


def notify_worker(kind: str, payload: str = "") -> None:
    msg = f"{kind}|{payload or ''}"
    client = _redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.lpush(WAKE_KEY, msg)
            pipe.ltrim(WAKE_KEY, 0, 1999)
            pipe.execute()
            return
        except Exception:
            logger.debug("redis wake failed; falling back to file", exc_info=True)
        finally:
            try:
                client.close()
            except Exception:
                pass
    try:
        _WAKE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _WAKE_FILE.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        logger.exception("file wake failed kind=%s", kind)


def write_heartbeat() -> None:
    now = str(time.time())
    client = _redis()
    if client is not None:
        try:
            client.set(HEARTBEAT_KEY, now, ex=60)
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass
    try:
        _HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEARTBEAT_FILE.write_text(now + "\n", encoding="utf-8")
    except OSError:
        pass


def publish_bandwidth(payload: dict) -> None:
    try:
        from app.sync.live import _drop_redis, _redis as live_redis
    except Exception:
        return
    client = live_redis()
    if client is None:
        return
    try:
        client.set(METRICS_BW_KEY, json.dumps(payload), ex=90)
    except Exception:
        _drop_redis()


def load_bandwidth() -> Optional[dict]:
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(METRICS_BW_KEY)
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def _handle(msg: str) -> None:
    kind, _, payload = (msg or "").partition("|")
    kind = kind.strip()
    payload = payload.strip()
    logger.info("worker wake kind=%s payload=%s", kind, payload or "-")
    if kind == "flush_finalmask":
        try:
            from app.wireguard.finalmask_reload import flush_finalmask_xray_reload

            flush_finalmask_xray_reload(urgent=True)
        except Exception:
            logger.exception("wake finalmask flush failed")
        return
    if kind in ("outbox", "user_change", "core_sync"):
        if kind in ("outbox", "user_change"):
            try:
                from app.sync.outbox import drain

                drain()
            except Exception:
                logger.exception("outbox drain on wake failed")
            if kind == "outbox":
                return
        from app.wireguard.operations import sync_user_change

        sync_user_change(immediate=True)
        try:
            from app.xray.serving import schedule_core_sync

            schedule_core_sync(delay=0.2)
        except Exception:
            logger.exception("wake core_sync failed")
        try:
            from app.wireguard.finalmask_reload import flush_finalmask_xray_reload

            flush_finalmask_xray_reload()
        except Exception:
            logger.exception("wake finalmask flush failed")
        return
    if kind == "connect_node" and payload:
        from app.xray.operations import connect_node

        connect_node(int(payload))
        return
    if kind == "converge_node" and payload:
        from app.sync.node_report import converge_node

        converge_node(int(payload))
        return
    if kind == "restart_node" and payload:
        from app.xray.operations import restart_node

        restart_node(int(payload))
        return
    if kind == "resync_fleet":
        apply_fleet_resync()
        return
    if kind == "converge_bulk" and payload:
        proto, _, job_id = payload.partition("|")
        proto = proto.strip() or "wireguard"
        job_id = job_id.strip()
        from app.wireguard.converge import converge_after_bulk_native, store_converge_result

        meta = converge_after_bulk_native(protocol=proto, wait_finalmask=True)
        if job_id:
            store_converge_result(job_id, meta)
        return
    if kind == "apply_tunnel" and payload:
        from app.db import GetDB
        from app.db.models import Tunnel
        from app.routers.tunnel import _apply_tunnel

        with GetDB() as db:
            row = db.query(Tunnel).filter(Tunnel.id == int(payload)).first()
            if row is None or not row.enabled:
                logger.warning("apply_tunnel wake: tunnel %s missing/disabled", payload)
                return
            _apply_tunnel(db, row, health=True)
        return
    if kind == "restart_core":
        from app import xray

        xray.core.restart(xray.config.include_db_users(), force=True)
        return
    if kind == "start_core":
        from app import xray

        if not getattr(xray.core, "started", False):
            xray.core.start(xray.config.include_db_users())
        return
    if kind == "stop_core":
        from app import xray

        if getattr(xray.core, "started", False):
            xray.core.stop()
        return
    logger.warning("unknown worker wake kind=%s", kind)


def _drain_file() -> None:
    if not _WAKE_FILE.is_file():
        return
    try:
        lines = _WAKE_FILE.read_text(encoding="utf-8").splitlines()
        _WAKE_FILE.write_text("", encoding="utf-8")
    except OSError:
        return
    seen = set()
    for line in lines:
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        try:
            _handle(line)
        except Exception:
            logger.exception("wake file handler failed: %s", line)


def _loop() -> None:
    while not _stop.is_set():
        write_heartbeat()
        client = _redis()
        if client is None:
            _drain_file()
            if _stop.wait(1.0):
                return
            continue
        try:
            item = client.brpop(WAKE_KEY, timeout=2)
        except Exception:
            _drain_file()
            if _stop.wait(1.0):
                return
            continue
        finally:
            try:
                client.close()
            except Exception:
                pass
        if not item:
            _drain_file()
            continue
        _, msg = item
        try:
            _handle(str(msg))
        except Exception:
            logger.exception("wake handler failed: %s", msg)


def start_wake_listener() -> None:
    global _listener
    if _listener is not None and _listener.is_alive():
        return
    _stop.clear()
    _listener = threading.Thread(target=_loop, name="worker-wake", daemon=True)
    _listener.start()


def stop_wake_listener() -> None:
    _stop.set()
