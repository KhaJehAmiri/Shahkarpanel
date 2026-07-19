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

logger = logging.getLogger("nexus-wg")

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
                from app.wireguard.operations import sync_all_nodes

                result["sync_nodes"] = int(sync_all_nodes() or 0)
            except Exception as exc:
                logger.exception("Bulk WireGuard converge failed")
                errors.append(f"wireguard: {exc}")
                result["sync_ok"] = False

            # Always push Finalmask after membership changes — even when kernel
            # sync failed. Prod nodes are Finalmask-only; skipping this left
            # bulk-assigned users with DB proxies but no live clients.
            if wait_finalmask:
                try:
                    from app.wireguard.finalmask_reload import (
                        flush_finalmask_xray_reload,
                        schedule_finalmask_xray_reload,
                    )

                    # Mark bulk so any nested schedule uses the longer debounce.
                    schedule_finalmask_xray_reload(delay=0.1, bulk=True)
                    flush_finalmask_xray_reload()
                    result["finalmask_reloaded"] = True
                except Exception as exc:
                    logger.exception("Bulk Finalmask flush failed")
                    errors.append(f"finalmask: {exc}")
                    result["sync_ok"] = False
            else:
                try:
                    from app.wireguard.finalmask_reload import schedule_finalmask_xray_reload

                    schedule_finalmask_xray_reload(bulk=True)
                except Exception as exc:
                    logger.warning("Bulk Finalmask schedule failed: %s", exc)

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
