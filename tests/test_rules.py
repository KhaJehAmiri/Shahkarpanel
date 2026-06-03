import app.rules as rules
from app import feature_flags as ff
from app.db import GetDB
from app.db.models import Rule
from app.events import EventType, publish, subscribe


def test_rule_engine_end_to_end():
    ff.set_flag("rule_engine", True)

    with GetDB() as db:
        db.add(
            Rule(
                name="republish-on-connect",
                enabled=True,
                trigger_event=EventType.node_connected.value,
                condition={"field": "node_id", "op": "eq", "value": 7},
                action="publish_event",
                action_params={"event_type": EventType.node_modified.value},
            )
        )
        db.commit()

    # Force (re)load now that the flag is on.
    rules._loaded = False
    rules.load_rules()

    captured = []
    subscribe(
        lambda e: captured.append(e.payload.get("node_id")),
        types=[EventType.node_modified],
    )

    publish(EventType.node_connected, {"node_id": 7})   # matches condition
    publish(EventType.node_connected, {"node_id": 1})   # condition fails

    assert 7 in captured
    assert 1 not in captured
