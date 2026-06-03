from datetime import datetime, timedelta

import app.cluster as cluster
from app import feature_flags as ff
from app import plugins
from app.db import GetDB, crud
from app.db.models import Node
from app.events import EventType, subscribe
from app.models.node import NodeCreate, NodeStatus


def test_node_group_and_clustering_fields_persist():
    with GetDB() as db:
        group = crud.create_node_group(db, name="eu-west", region="EU")
        node = crud.create_node(
            db,
            NodeCreate(
                name="node-eu-1",
                address="10.0.0.1",
                region="EU",
                group_id=group.id,
                capacity=500,
            ),
        )
        assert node.region == "EU"
        assert node.group_id == group.id
        assert node.capacity == 500
        assert any(g.name == "eu-west" for g in crud.get_node_groups(db))


def test_failover_reports_down_node_once():
    with GetDB() as db:
        node = Node(
            name="node-down-1",
            address="2.2.2.2",
            port=62050,
            api_port=62051,
            status=NodeStatus.error,
            last_status_change=datetime.utcnow() - timedelta(hours=1),
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        node_id = node.id

    seen = []
    subscribe(lambda e: seen.append(e.payload.get("node_id")), types=[EventType.node_down])

    cluster._reported_down.clear()
    cluster.detect_failures()
    cluster.detect_failures()  # must NOT re-report the same outage

    assert seen.count(node_id) == 1


def test_auto_heal_plugin_loads_independently():
    ff.set_flag("auto_healing", True)
    plugins._loaded = False
    plugins._registry.clear()
    plugins.load_plugins()
    assert "auto_heal" in {p.name for p in plugins.get_plugins()}
