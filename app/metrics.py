"""Prometheus metrics exporter.

Renders panel, user, bandwidth and node metrics in the Prometheus text format.
A fresh registry is built on each scrape so the gauges always reflect current
state without long-lived global collectors.
"""
import logging

from prometheus_client import CollectorRegistry, Gauge, Info, generate_latest

logger = logging.getLogger("uvicorn.error")


def render_metrics() -> bytes:
    registry = CollectorRegistry()

    from app import __version__
    from app.db import GetDB, crud
    from app.models.node import NodeStatus
    from app.models.user import UserStatus

    Info("nexuspanel", "NexusPanel information", registry=registry).info(
        {"version": __version__}
    )

    users_gauge = Gauge(
        "nexuspanel_users", "Number of users by status", ["status"], registry=registry
    )
    online_gauge = Gauge(
        "nexuspanel_online_users", "Users seen online in the last 24h", registry=registry
    )
    bandwidth_gauge = Gauge(
        "nexuspanel_bandwidth_bytes_total",
        "Total system bandwidth in bytes",
        ["direction"],
        registry=registry,
    )
    node_connected_gauge = Gauge(
        "nexuspanel_node_connected",
        "Whether a node is connected (1) or not (0)",
        ["node_id", "name"],
        registry=registry,
    )
    node_bandwidth_gauge = Gauge(
        "nexuspanel_node_bandwidth_bytes_total",
        "Total per-node bandwidth in bytes",
        ["node_id", "name", "direction"],
        registry=registry,
    )

    with GetDB() as db:
        for status in UserStatus:
            users_gauge.labels(status=status.value).set(
                crud.get_users_count(db, status=status)
            )

        online_gauge.set(crud.count_online_users(db, 24))

        system = crud.get_system_usage(db)
        bandwidth_gauge.labels(direction="uplink").set(getattr(system, "uplink", 0) or 0)
        bandwidth_gauge.labels(direction="downlink").set(getattr(system, "downlink", 0) or 0)

        for node in crud.get_nodes(db):
            labels = {"node_id": str(node.id), "name": node.name or ""}
            node_connected_gauge.labels(**labels).set(
                1 if node.status == NodeStatus.connected else 0
            )
            node_bandwidth_gauge.labels(**labels, direction="uplink").set(node.uplink or 0)
            node_bandwidth_gauge.labels(**labels, direction="downlink").set(node.downlink or 0)

    return generate_latest(registry)
