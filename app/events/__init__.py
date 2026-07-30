"""Shahkar event bus.

A small publish/subscribe layer that decouples *producing* events (a user was
created, a node went down) from *consuming* them (webhooks, Telegram, plugins,
rules). It replaces the previous behaviour where events were only created when
``WEBHOOK_ADDRESS`` was configured and otherwise silently dropped.

Usage::

    from app.events import publish, subscribe, EventType

    subscribe(my_handler, types=[EventType.node_error])
    publish(EventType.node_error, {"node_id": 3, "message": "timeout"})
"""
import logging
from typing import Iterable, Optional

from config import REDIS_URL

from .bus import Event, EventBus, Handler
from .types import EventType

logger = logging.getLogger("uvicorn.error")

event_bus = EventBus()

if REDIS_URL:
    try:
        from .redis_backend import build_redis_sink

        event_bus.set_sink(build_redis_sink(REDIS_URL))
    except Exception:
        logger.exception("Failed to initialise Redis event sink; "
                         "continuing with in-process bus only")


def publish(event_type: EventType, payload: Optional[dict] = None) -> None:
    """Publish a raw event by type and payload."""
    event_bus.publish(Event(event_type, payload or {}))


def subscribe(handler: Handler, types: Optional[Iterable[EventType]] = None) -> Handler:
    """Register an event handler, optionally filtered to specific types."""
    return event_bus.subscribe(handler, types)


def publish_notification(notification) -> None:
    """Bridge a legacy ``Notification`` object onto the event bus.

    Called from :func:`app.utils.notification.notify` so every notification —
    not just the ones destined for a webhook — reaches bus subscribers.
    """
    from fastapi.encoders import jsonable_encoder

    event_type = EventType.from_value(getattr(notification.action, "value", None))
    if event_type is None:
        return

    event_bus.publish(
        Event(event_type, {"notification": jsonable_encoder(notification)})
    )


__all__ = [
    "event_bus",
    "EventBus",
    "Event",
    "EventType",
    "publish",
    "subscribe",
    "publish_notification",
]
