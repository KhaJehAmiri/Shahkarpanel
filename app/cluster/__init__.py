"""Cluster reliability: failover detection.

A lightweight, opt-in detector that flags nodes which have been in the ``error``
state longer than ``CLUSTER_NODE_DOWN_SECONDS`` and publishes a ``node_down``
event exactly once per outage. Acting on that event (restart, migrate, notify)
is delegated to the rule engine / auto-heal plugin, keeping this module
non-destructive unless ``CLUSTER_AUTO_DISABLE_DOWN_NODES`` is explicitly set.
"""
import logging
from datetime import datetime, timedelta

from app.events import EventType, publish
from config import CLUSTER_AUTO_DISABLE_DOWN_NODES, CLUSTER_NODE_DOWN_SECONDS

logger = logging.getLogger("uvicorn.error")

# Nodes already reported as down (to emit node_down only once per outage).
_reported_down: set = set()


def detect_failures() -> None:
    from app.db import GetDB, crud
    from app.models.node import NodeStatus

    cutoff = datetime.utcnow() - timedelta(seconds=CLUSTER_NODE_DOWN_SECONDS)

    with GetDB() as db:
        error_nodes = crud.get_nodes(db, status=NodeStatus.error)
        for node in error_nodes:
            if not node.last_status_change or node.last_status_change > cutoff:
                continue
            if node.id in _reported_down:
                continue

            _reported_down.add(node.id)
            publish(
                EventType.node_down,
                {
                    "node_id": node.id,
                    "name": node.name,
                    "group_id": node.group_id,
                    "down_since": node.last_status_change.isoformat(),
                },
            )
            logger.warning("[cluster] node '%s' considered down (failover)", node.name)

            if CLUSTER_AUTO_DISABLE_DOWN_NODES:
                crud.update_node_status(
                    db, node, NodeStatus.disabled, message="Auto-disabled by failover"
                )
                try:
                    from app import xray

                    xray.operations.remove_node(node.id)
                except Exception:
                    logger.exception("[cluster] failed to remove disabled node %s", node.id)

        # Forget nodes that have recovered so future outages are reported again.
        recovered = {n.id for n in crud.get_nodes(db) if n.status == NodeStatus.connected}
        _reported_down.difference_update(recovered)
