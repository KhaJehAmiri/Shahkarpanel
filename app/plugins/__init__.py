"""Plugin registry and loader.

Plugins are gated behind the ``plugins`` feature flag. When enabled, built-in
plugins are instantiated and subscribed to the event bus. Loading is idempotent.
"""
import logging
from typing import Dict, List

from app import feature_flags
from app.events import subscribe

from .base import Plugin

logger = logging.getLogger("uvicorn.error")

_registry: Dict[str, Plugin] = {}
_loaded = False


def register(plugin: Plugin) -> None:
    _registry[plugin.name] = plugin


def get_plugins() -> List[Plugin]:
    return list(_registry.values())


def load_plugins() -> None:
    """Instantiate and wire built-in plugins. Safe to call more than once."""
    global _loaded
    if _loaded:
        return

    from .builtin import BUILTIN_PLUGINS, AutoHealPlugin

    plugin_classes = []
    if feature_flags.is_enabled("plugins"):
        plugin_classes.extend(BUILTIN_PLUGINS)
    # Auto-healing can be enabled independently of the general plugin system.
    if feature_flags.is_enabled("auto_healing"):
        plugin_classes.append(AutoHealPlugin)

    if not plugin_classes:
        logger.info("Plugin system disabled (flags 'plugins' and 'auto_healing' are off)")
        _loaded = True
        return

    for plugin_cls in plugin_classes:
        try:
            plugin = plugin_cls()
            plugin.setup()
            register(plugin)
            subscribe(plugin.on_event, types=plugin.events())
            logger.info("Loaded plugin: %s", plugin.name)
        except Exception:
            logger.exception("Failed to load plugin %s", plugin_cls)

    _loaded = True


__all__ = ["Plugin", "register", "get_plugins", "load_plugins"]
