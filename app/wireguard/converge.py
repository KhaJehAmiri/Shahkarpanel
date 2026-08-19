"""Synchronous dataplane converge after bulk membership changes.

Bulk APIs historically returned ``applied`` as soon as the DB committed, while
WireGuard / Finalmask / sing-box sync ran on daemon threads. Operators read
that as “peers are live.” This helper runs the sync **inline** (single-flight)
so the API can report whether nodes actually accepted the peer set.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("shahkar-wg")

_lock = threading.Lock()


def converge_after_bulk_native(
    *,
    protocol: str,
    wait_finalmask: bool = True,
) -> Dict[str, Any]:
    """Push native protocol changes to nodes; return sync metadata for the API.

    ``protocol`` is a ``BulkNativeProtocol`` value (wireguard / amneziawg / both /
    hysteria2 / tuic / anytls).
    """
    started = time.perf_counter()
    result: Dict[str, Any] = {
        "sync_pending": False,
        "sync_ok": True,
        "sync_nodes": 0,
        "finalmask_reloaded": False,
        "singbox_nodes": 0,
        "sync_error": None,
        "sync_ms": 0,
    }

    needs_wg = protocol in ("wireguard", "amneziawg", "both")
    needs_singbox = protocol in ("hysteria2", "tuic", "anytls")

    # Serialize bulk converges so two overlapping bulk ops cannot interleave
    # apply_specs / Xray restarts on the same nodes.
    with _lock:
        errors: list[str] = []
        if needs_wg:
            try:
                from app.wireguard.operations import sync_user_change

                # Immediate+urgent: parallel Finalmask hot-replace. Full
                # ``sync_all_nodes()`` serialises RPyC across the fleet and
                # made Bulk Assign appear hung while nodes sat "busy".
                sync_user_change(immediate=True, urgent=wait_finalmask)
                result["sync_nodes"] = 1
                result["finalmask_reloaded"] = bool(wait_finalmask)
            except Exception as exc:
                logger.exception("Bulk WireGuard converge failed")
                errors.append(f"wireguard: {exc}")
                result["sync_ok"] = False

        if needs_singbox:
            try:
                from app.singbox.operations import sync_all_nodes as singbox_sync_all

                result["singbox_nodes"] = int(singbox_sync_all() or 0)
            except Exception as exc:
                logger.exception("Bulk sing-box converge failed")
                errors.append(f"singbox: {exc}")
                result["sync_ok"] = False

        if errors:
            result["sync_error"] = "; ".join(errors)[:500]

        result["sync_ms"] = int((time.perf_counter() - started) * 1000)
        logger.info(
            "bulk converge protocol=%s ok=%s wg_nodes=%s singbox_nodes=%s finalmask=%s %sms",
            protocol,
            result["sync_ok"],
            result["sync_nodes"],
            result["singbox_nodes"],
            result["finalmask_reloaded"],
            result["sync_ms"],
        )
        return result


def pending_sync_meta() -> Dict[str, Any]:
    """Metadata when the caller opts out of waiting (fire-and-forget)."""
    return {
        "sync_pending": True,
        "sync_ok": None,
        "sync_nodes": 0,
        "finalmask_reloaded": False,
        "singbox_nodes": 0,
        "sync_error": None,
        "sync_ms": 0,
    }


_RESULT_KEY = "shahkar:bulk:converge:{job}"
_WAIT_TIMEOUT_SEC = 25.0


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


def store_converge_result(job_id: str, meta: Dict[str, Any]) -> None:
    client = _redis()
    if client is None or not job_id:
        return
    try:
        import json

        client.set(_RESULT_KEY.format(job=job_id), json.dumps(meta), ex=90)
    except Exception:
        logger.debug("bulk converge result store failed", exc_info=True)
    finally:
        try:
            client.close()
        except Exception:
            pass


def wait_converge_result(job_id: str, timeout: float = _WAIT_TIMEOUT_SEC) -> Optional[Dict[str, Any]]:
    client = _redis()
    if client is None or not job_id:
        return None
    try:
        import json

        deadline = time.monotonic() + max(1.0, float(timeout))
        key = _RESULT_KEY.format(job=job_id)
        while time.monotonic() < deadline:
            raw = client.get(key)
            if raw:
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
            time.sleep(0.2)
        return None
    except Exception:
        logger.debug("bulk converge result wait failed", exc_info=True)
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def request_bulk_converge(*, protocol: str, wait: bool = True) -> Dict[str, Any]:
    """Run native dataplane converge on the worker; API never walks xray.nodes.

    ``wait=True`` blocks HTTP until the worker writes a result (bounded), so
    Bulk Assign can report whether peers actually landed.
    """
    proto = (protocol or "wireguard").strip() or "wireguard"
    from app.runtime_role import owns_control_plane

    if owns_control_plane():
        return converge_after_bulk_native(protocol=proto, wait_finalmask=True)

    import uuid

    from app.sync.wake import notify_worker

    job_id = uuid.uuid4().hex[:16]
    notify_worker("converge_bulk", f"{proto}|{job_id}")
    if not wait:
        return pending_sync_meta()
    meta = wait_converge_result(job_id)
    if not meta:
        out = pending_sync_meta()
        out["sync_error"] = "worker still applying"
        return out
    return meta
