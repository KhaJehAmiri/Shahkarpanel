"""Apply enabled services to a node: materialize, hosts, push to agent."""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from app.services.hosts_sync import sync_hosts_for_node
from app.services.materialize import materialize_node_services

logger = logging.getLogger("nexus-services-apply")


def set_node_services(
    db,
    dbnode,
    slugs: Iterable[str],
    *,
    replace: bool = True,
) -> List[str]:
    """Enable the given service slugs on a node and materialize engine config."""
    from app.db import crud

    enabled = crud.set_node_service_bindings(db, dbnode.id, list(slugs), replace=replace)
    materialize_node_services(db, dbnode)
    db.refresh(dbnode)

    xray_on = "xray" in enabled or any(
        s.startswith("xray-inbound-") for s in enabled
    )
    sync_hosts_for_node(db, dbnode, xray_enabled=xray_on)
    return enabled


def apply_node_services(node_id: int, *, reconnect: bool = True) -> bool:
    """Re-materialize and push config to a connected node."""
    from app.db import GetDB, crud

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if not dbnode:
            return False
        materialize_node_services(db, dbnode)
        bindings = crud.get_node_service_bindings(db, node_id, enabled_only=True)
        slugs = [b.service_slug for b in bindings]
        xray_on = "xray" in slugs
        sync_hosts_for_node(db, dbnode, xray_enabled=xray_on)

    if not reconnect:
        return True

    try:
        from app import xray

        if node_id in xray.nodes and xray.nodes[node_id].connected:
            from app.xray import operations as xops

            xops.restart_node(node_id)
        else:
            from app.xray.operations import connect_node

            connect_node(node_id)
        return True
    except Exception as exc:
        logger.warning("apply_node_services reconnect failed for %s: %s", node_id, exc)
        return False


def apply_services_after_provision(
    db,
    dbnode,
    slugs: List[str],
    *,
    extras=None,
) -> None:
    """Called from post_install after agent registers."""
    if not slugs:
        return
    set_node_services(db, dbnode, slugs, replace=False)
    materialize_node_services(db, dbnode)
