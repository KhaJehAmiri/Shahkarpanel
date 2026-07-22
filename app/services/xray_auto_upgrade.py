"""Automatically upgrade panel + Xray nodes to the latest Xray-core release."""
from __future__ import annotations

import logging
from typing import Any

from config import (
    XRAY_AUTO_UPGRADE_ENABLED,
    XRAY_AUTO_UPGRADE_INCLUDE_PRERELEASE,
)

logger = logging.getLogger("nexus-xray-auto-upgrade")


def run_xray_auto_upgrade(*, force: bool = False) -> dict[str, Any]:
    """Check GitHub for a newer Xray-core and upgrade panel + connected Xray nodes."""
    from app.utils.runtime_settings import xray_auto_upgrade_config

    cfg = xray_auto_upgrade_config()
    if not cfg["enabled"] and not force:
        return {"skipped": True, "reason": "disabled"}

    from app.utils.xray_releases import is_version_older, latest_xray_tag

    tag = latest_xray_tag(include_prerelease=cfg["include_prerelease"])
    if not tag:
        logger.warning("xray auto-upgrade: no release tag from GitHub")
        return {"skipped": True, "reason": "no_release"}

    result: dict[str, Any] = {"tag": tag, "panel": None, "nodes": {}}

    result["panel"] = _upgrade_panel_if_needed(tag, force=force)
    result["nodes"] = _upgrade_xray_nodes(tag, force=force)

    upgraded = bool(result["panel"]) or any(result["nodes"].values())
    if upgraded:
        logger.info("xray auto-upgrade finished tag=%s result=%s", tag, result)
    else:
        logger.debug("xray auto-upgrade: already on %s", tag)
    return result


def _upgrade_panel_if_needed(tag: str, *, force: bool) -> str | None:
    from app import xray
    from app.utils import xray_upgrade as xu
    from app.utils.xray_releases import is_version_older

    current = xu.read_version() or xray.core.version
    if not force and not is_version_older(current, tag):
        return None

    logger.info("xray auto-upgrade: panel %s -> %s", current, tag)
    was_running = bool(xray.core.started)
    version_line = xu.install_xray_release(tag, stop_running=True)
    xray.core.version = xray.core.get_version()
    if was_running:
        try:
            xray.core.restart(xray.config.include_db_users())
        except Exception as exc:
            logger.error("xray auto-upgrade: panel restart failed after install: %s", exc)
            raise
    else:
        logger.info(
            "xray auto-upgrade: panel binary updated (core was not tracked as running; skipped restart)",
        )
    return version_line


def _upgrade_xray_nodes(tag: str, *, force: bool) -> dict[int, str | None]:
    from app import xray
    from app.db import GetDB, crud
    from app.models.node import CoreKind, NodeStatus
    from app.utils.xray_releases import is_version_older
    from app.xray import operations as xray_ops
    from app.xray.node import XRayNode
    from app.xray.operations import get_tls

    outcomes: dict[int, str | None] = {}
    config = None

    with GetDB() as db:
        dbnodes = crud.get_nodes(db, enabled=True)

    for dbnode in dbnodes:
        current = dbnode.xray_version
        if not force and not is_version_older(current, tag):
            continue

        node_id = dbnode.id
        is_wg_node = (dbnode.core_kind or CoreKind.xray.value) == CoreKind.wireguard.value
        logger.info(
            "xray auto-upgrade: node %s (%s) %s -> %s",
            node_id,
            dbnode.name,
            current,
            tag,
        )
        try:
            tls = get_tls()
            remote = XRayNode(
                address=dbnode.address,
                port=dbnode.port,
                api_port=dbnode.api_port,
                ssl_key=tls["key"],
                ssl_cert=tls["certificate"],
                usage_coefficient=dbnode.usage_coefficient or 1,
            )
            live_version = remote.upgrade_xray(tag)
            try:
                # WireGuard/Finalmask nodes must rebuild from their own bake
                # (build_node_xray_config via restart_node), not the panel VLESS config.
                if is_wg_node:
                    xray_ops.restart_node(node_id)
                else:
                    if config is None:
                        config = xray.config.include_db_users()
                    xray_ops.restart_node(node_id, config)
            except Exception as exc:
                logger.warning(
                    "xray auto-upgrade: node %s upgraded but restart failed: %s",
                    node_id,
                    exc,
                )
            with GetDB() as db:
                dbnode = crud.get_node_by_id(db, node_id)
                if dbnode:
                    crud.update_node_status(
                        db,
                        dbnode,
                        dbnode.status or NodeStatus.connected,
                        version=live_version,
                    )
            outcomes[node_id] = live_version
        except Exception as exc:
            logger.error(
                "xray auto-upgrade: node %s (%s) failed: %s",
                node_id,
                dbnode.name,
                exc,
            )
            outcomes[node_id] = None
    return outcomes
