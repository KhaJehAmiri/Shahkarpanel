import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Set, Tuple

from .types import EventType

logger = logging.getLogger("uvicorn.error")


@dataclass
class Event:
    """A single event flowing through the bus."""

    type: EventType
    payload: dict = field(default_factory=dict)


# A subscriber is a callable that receives an Event. A sink is the same shape
# but is meant for durable/cross-process fan-out (e.g. Redis Streams).
Handler = Callable[[Event], None]
Sink = Callable[[Event], None]


class EventBus:
    """In-process publish/subscribe hub with an optional external sink.

    Local subscribers run synchronously in the publishing thread. The optional
    sink (set via :meth:`set_sink`) receives every event too and is where a
    Redis Streams backend hooks in, making the bus ready for multi-panel/HA
    consumption without changing producer code.
    """

    def __init__(self) -> None:
        self._subscribers: List[Tuple[Handler, Optional[Set[EventType]]]] = []
        self._sink: Optional[Sink] = None

    def set_sink(self, sink: Optional[Sink]) -> None:
        self._sink = sink

    def subscribe(
        self, handler: Handler, types: Optional[Iterable[EventType]] = None
    ) -> Handler:
        """Register a handler, optionally filtered to specific event types."""
        self._subscribers.append((handler, set(types) if types else None))
        return handler

    def publish(self, event: Event) -> None:
        for handler, types in list(self._subscribers):
            if types is not None and event.type not in types:
                continue
            try:
                handler(event)
            except Exception:
                logger.exception("Event subscriber failed for %s", event.type)

        if self._sink is not None:
            try:
                self._sink(event)
            except Exception:
                logger.exception("Event sink failed for %s", event.type)
