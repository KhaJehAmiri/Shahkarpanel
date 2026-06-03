"""Actions executed by the rule engine when a rule matches.

Actions are referenced by name from the ``rules`` table. Each handler receives
the resolved ``params`` dict and the triggering :class:`~app.events.Event`.
"""
import logging
from typing import Callable, Dict

from app.events import Event, EventType, publish

logger = logging.getLogger("uvicorn.error")

ActionHandler = Callable[[dict, Event], None]


def _action_log(params: dict, event: Event) -> None:
    message = params.get("message", "rule matched")
    logger.info("[rule] %s (event=%s payload=%s)", message, event.type.value, event.payload)


def _action_publish_event(params: dict, event: Event) -> None:
    target = EventType.from_value(params.get("event_type"))
    if target is None:
        logger.warning("[rule] publish_event: unknown event_type %r", params.get("event_type"))
        return
    payload = dict(event.payload)
    payload.update(params.get("payload", {}))
    publish(target, payload)


def _action_restart_node(params: dict, event: Event) -> None:
    node_id = params.get("node_id") or event.payload.get("node_id")
    if node_id is None:
        logger.warning("[rule] restart_node: no node_id available")
        return
    from app import xray

    xray.operations.restart_node(int(node_id))


_ACTIONS: Dict[str, ActionHandler] = {
    "log": _action_log,
    "publish_event": _action_publish_event,
    "restart_node": _action_restart_node,
}


def available_actions() -> list:
    return sorted(_ACTIONS.keys())


def run_action(action: str, params: dict, event: Event) -> None:
    handler = _ACTIONS.get(action)
    if handler is None:
        logger.warning("[rule] unknown action %r", action)
        return
    handler(params or {}, event)
