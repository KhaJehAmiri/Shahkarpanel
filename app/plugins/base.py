"""Base class for NexusPanel plugins.

A plugin reacts to events on the event bus. Built-in plugins are registered at
startup; the architecture leaves room for external/marketplace plugins later
(phase 5) without changing this contract.
"""
from typing import Iterable, Optional

from app.events import Event, EventType


class Plugin:
    #: Unique, stable identifier.
    name: str = "plugin"
    #: Human-readable description shown in the UI / API.
    description: str = ""

    def events(self) -> Optional[Iterable[EventType]]:
        """Event types this plugin subscribes to. ``None`` means all events."""
        return None

    def setup(self) -> None:
        """Optional one-time initialisation when the plugin is loaded."""

    def on_event(self, event: Event) -> None:  # pragma: no cover - overridden
        """Handle an event. Must be implemented by concrete plugins."""
        raise NotImplementedError
