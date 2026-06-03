from types import SimpleNamespace

import app.workflows as workflows
from app import feature_flags as ff
from app import ha, protocols, routing
from app.db import GetDB
from app.db.models import Workflow
from app.events import EventType, publish, subscribe
from app.models.node import NodeStatus


def _node(id, latency=None, region=None, capacity=None, status=NodeStatus.connected):
    return SimpleNamespace(
        id=id, name=f"n{id}", latency_ms=latency, region=region,
        capacity=capacity, status=status,
    )


# ---- Smart routing ----

def test_routing_by_latency_orders_fastest_first():
    nodes = [_node(1, latency=120), _node(2, latency=15), _node(3, latency=None)]
    ordered = routing.select_nodes(nodes, strategy="latency")
    assert [n.id for n in ordered] == [2, 1, 3]


def test_routing_by_region_prefers_same_region():
    nodes = [_node(1, latency=10, region="US"), _node(2, latency=50, region="EU")]
    ordered = routing.select_nodes(nodes, strategy="region", region="EU")
    assert ordered[0].id == 2


def test_routing_excludes_unusable_nodes():
    nodes = [_node(1, latency=10), _node(2, latency=5, status=NodeStatus.error)]
    ordered = routing.select_nodes(nodes, strategy="latency")
    assert [n.id for n in ordered] == [1]


def test_routing_limit_applies():
    nodes = [_node(i, latency=i) for i in range(1, 6)]
    assert len(routing.select_nodes(nodes, strategy="latency", limit=2)) == 2


# ---- HA ----

def test_run_if_leader_executes_when_leader():
    assert ha.is_leader() is True  # single instance / HA disabled
    calls = []
    wrapped = ha.run_if_leader(lambda: calls.append(1))
    wrapped()
    assert calls == [1]


def test_run_if_leader_skips_when_follower(monkeypatch):
    monkeypatch.setattr(ha, "is_leader", lambda: False)
    calls = []
    ha.run_if_leader(lambda: calls.append(1))()
    assert calls == []


# ---- Multi-protocol abstraction ----

def test_xray_backend_is_available_and_serves_vless():
    xray = protocols.get_backend("xray")
    assert xray is not None and xray.available
    assert xray.supports("vless")
    assert protocols.backend_for_protocol("vless").name == "xray"


def test_planned_backends_registered_but_unavailable():
    names = {b.name for b in protocols.all_backends()}
    assert {"sing-box", "hysteria2", "tuic"}.issubset(names)
    assert protocols.get_backend("sing-box").available is False


# ---- Workflow engine ----

def test_workflow_runs_steps_in_order():
    ff.set_flag("workflows", True)

    with GetDB() as db:
        db.add(
            Workflow(
                name="multi-step",
                enabled=True,
                trigger_event=EventType.node_connected.value,
                condition={"field": "node_id", "op": "eq", "value": 42},
                steps=[
                    {"action": "log", "params": {"message": "step1"}},
                    {"action": "publish_event",
                     "params": {"event_type": EventType.node_modified.value}},
                ],
            )
        )
        db.commit()

    workflows._loaded = False
    workflows.load_workflows()

    captured = []
    subscribe(
        lambda e: captured.append(e.payload.get("node_id")),
        types=[EventType.node_modified],
    )

    publish(EventType.node_connected, {"node_id": 42})
    publish(EventType.node_connected, {"node_id": 1})

    assert 42 in captured
    assert 1 not in captured
