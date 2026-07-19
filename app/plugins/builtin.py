"""Built-in plugins shipped with the panel."""
import logging

from app.events import Event, EventType

from .base import Plugin

logger = logging.getLogger("uvicorn.error")


class EventLogPlugin(Plugin):
    name = "event_log"
    description = "Logs every event published on the bus (useful for debugging)."

    def on_event(self, event: Event) -> None:
        logger.info("[event] %s %s", event.type.value, event.payload)


class NodeAlertPlugin(Plugin):
    name = "node_alert"
    description = "Emits a warning log whenever a node reports an error."

    def events(self):
        return [EventType.node_error]

    def on_event(self, event: Event) -> None:
        logger.warning(
            "[node-alert] node %s error: %s",
            event.payload.get("node_id"),
            event.payload.get("message"),
        )


class AutoHealPlugin(Plugin):
    name = "auto_heal"
    description = "Restarts a node when it errors or goes down (with a cooldown)."

    #: Minimum seconds between restart attempts for the same node.
    # Keep this high: on small WG nodes Finalmask peer pushes often flap as
    # ``node_error`` and a short cooldown turns into a restart storm that
    # makes the whole panel feel laggy (jobs skipped, core thrash).
    cooldown_seconds = 300

    def __init__(self) -> None:
        self._last_attempt: dict = {}

    def events(self):
        return [EventType.node_error, EventType.node_down]

    def on_event(self, event: Event) -> None:
        import time

        node_id = event.payload.get("node_id")
        if node_id is None:
            return

        now = time.time()
        if now - self._last_attempt.get(node_id, 0) < self.cooldown_seconds:
            return
        self._last_attempt[node_id] = now

        from app import xray

        logger.info("[auto-heal] restarting node %s after %s", node_id, event.type.value)
        try:
            xray.operations.restart_node(int(node_id))
        except Exception:
            logger.exception("[auto-heal] failed to restart node %s", node_id)


# Plugins loaded when the plugin system is enabled.
BUILTIN_PLUGINS = [EventLogPlugin, NodeAlertPlugin]

