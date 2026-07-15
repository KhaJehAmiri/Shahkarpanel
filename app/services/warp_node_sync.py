"""Push WARP TPROXY diversion to a node agent (kernel WG → Xray WARP)."""
from __future__ import annotations

from app import logger
from app.services.warp_tproxy import (
    node_wg_client_interfaces,
    node_wg_client_subnets,
    warp_tproxy_port,
)
from app.wireguard.transport import client_for_node


def sync_node_warp_tproxy(dbnode, *, node_object=None) -> bool:
    """Enable/disable host TPROXY for this node's WG client subnets.

    Best-effort: older node agents without ``wg_warp_tproxy`` are skipped with
    a warning. Xray-native (Finalmask) WARP still works via config push alone.
    """
    from app import xray

    node_object = node_object
    if node_object is None:
        node_object = xray.nodes.get(dbnode.id)
    client = client_for_node(node_object)
    if client is None:
        logger.warning(
            "WARP TPROXY sync skipped for node %s: no transport",
            dbnode.id,
        )
        return False

    apply = getattr(client, "apply_warp_tproxy", None)
    if apply is None:
        logger.warning(
            "WARP TPROXY sync skipped for node %s: agent has no wg_warp_tproxy "
            "(update nexusnode). Finalmask/Xray path still uses WARP.",
            dbnode.id,
        )
        return False

    enabled = bool(getattr(dbnode, "warp_enabled", False))
    try:
        ok = apply(
            enabled=enabled,
            subnets=node_wg_client_subnets(dbnode) if enabled else [],
            port=warp_tproxy_port(dbnode.id),
            interfaces=node_wg_client_interfaces(dbnode) if enabled else [],
        )
        return bool(ok)
    except Exception as exc:
        logger.warning(
            "WARP TPROXY sync failed for node %s: %s",
            dbnode.id,
            exc,
        )
        return False
