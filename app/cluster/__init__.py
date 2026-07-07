"""Cluster reliability: failover detection and self-heal.

An opt-in detector that flags nodes stuck in the ``error`` state longer than
``CLUSTER_NODE_DOWN_SECONDS``. For each such node it now performs *real* failover
actions rather than only emitting an event:

  1. Self-heal: attempt an automatic reconnect (``CLUSTER_AUTO_RECONNECT_DOWN_NODES``)
     for transient outages before declaring the node down.
  2. Failover routing hint: the ``node_down`` event carries the healthy fallback
     nodes in the same group so routing/subscription can steer users away.
  3. Optional auto-disable (``CLUSTER_AUTO_DISABLE_DOWN_NODES``) removes the node
     from the live registry so it stops receiving traffic.
  4. Recovery: a ``node_recovered`` event fires once a previously-down node comes
     back ``connected``.
"""
import logging
from datetime import datetime, timedelta

from app.events import EventType, publish
from config import (CLUSTER_AUTO_DISABLE_DOWN_NODES,
                    CLUSTER_AUTO_RECONNECT_DOWN_NODES, CLUSTER_NODE_DOWN_SECONDS)

logger = logging.getLogger("uvicorn.error")

# Nodes already reported as down (to emit node_down only once per outage).
_reported_down: set = set()
# Nodes we already tried to auto-reconnect this outage (one attempt per outage).
_reconnect_attempted: set = set()


def _healthy_fallbacks(db, crud, NodeStatus, node) -> list:
    """Healthy connected nodes that can absorb ``node``'s traffic.

    Prefers same-group nodes; falls back to any connected node so a single-group
    outage still has somewhere to route.
    """
    connected = [n for n in crud.get_nodes(db) if n.status == NodeStatus.connected and n.id != node.id]
    same_group = [n for n in connected if node.group_id and n.group_id == node.group_id]
    chosen = same_group or connected
    return [{"id": n.id, "name": n.name, "group_id": n.group_id} for n in chosen]


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

            # Self-heal first: a single reconnect attempt per outage. If the node
            # was just restarting or had a transient network blip this recovers
            # it without operator involvement or a disruptive disable.
            if CLUSTER_AUTO_RECONNECT_DOWN_NODES and node.id not in _reconnect_attempted:
                _reconnect_attempted.add(node.id)
                try:
                    from app import xray

                    logger.info("[cluster] attempting auto-reconnect for down node '%s'", node.name)
                    xray.operations.connect_node(node_id=node.id)
                    # Give the async reconnect a cycle to land before declaring
                    # the node down; if it fails we'll catch it next tick.
                    continue
                except Exception:
                    logger.exception("[cluster] auto-reconnect failed for node %s", node.id)

            _reported_down.add(node.id)
            fallbacks = _healthy_fallbacks(db, crud, NodeStatus, node)
            publish(
                EventType.node_down,
                {
                    "node_id": node.id,
                    "name": node.name,
                    "group_id": node.group_id,
                    "down_since": node.last_status_change.isoformat(),
                    "fallback_nodes": fallbacks,
                },
            )
            logger.warning(
                "[cluster] node '%s' considered down (failover); %d healthy fallback(s)",
                node.name,
                len(fallbacks),
            )

            if CLUSTER_AUTO_DISABLE_DOWN_NODES:
                crud.update_node_status(
                    db, node, NodeStatus.disabled, message="Auto-disabled by failover"
                )
                try:
                    from app import xray

                    xray.operations.remove_node(node.id)
                except Exception:
                    logger.exception("[cluster] failed to remove disabled node %s", node.id)

        # Forget nodes that have recovered so future outages are reported again,
        # and announce the recovery once.
        recovered = {n.id for n in crud.get_nodes(db) if n.status == NodeStatus.connected}
        for node_id in list(_reported_down & recovered):
            node = crud.get_node_by_id(db, node_id)
            publish(
                EventType.node_recovered,
                {"node_id": node_id, "name": node.name if node else None},
            )
            logger.info("[cluster] node %s recovered", node_id)
        _reported_down.difference_update(recovered)
        _reconnect_attempted.difference_update(recovered)
