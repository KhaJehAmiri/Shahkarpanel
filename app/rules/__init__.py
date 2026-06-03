"""Rule engine.

Subscribes to the event bus and, for each event, runs every enabled rule whose
``trigger_event`` matches and whose ``condition`` evaluates true. Gated behind
the ``rule_engine`` feature flag.
"""
import logging

from app import feature_flags
from app.events import Event, subscribe

from .actions import available_actions, run_action
from .conditions import evaluate

logger = logging.getLogger("uvicorn.error")

_loaded = False


def _handle_event(event: Event) -> None:
    from app.db import GetDB
    from app.db.models import Rule

    with GetDB() as db:
        rows = (
            db.query(Rule)
            .filter(Rule.enabled.is_(True), Rule.trigger_event == event.type.value)
            .all()
        )
        rules = [(r.name, r.condition, r.action, r.action_params) for r in rows]

    for name, condition, action, params in rules:
        try:
            if evaluate(condition, event.payload):
                run_action(action, params or {}, event)
        except Exception:
            logger.exception("Rule '%s' failed", name)


def load_rules() -> None:
    """Wire the rule engine to the event bus. Safe to call more than once."""
    global _loaded
    if _loaded:
        return

    if not feature_flags.is_enabled("rule_engine"):
        logger.info("Rule engine disabled (feature flag 'rule_engine' is off)")
        _loaded = True
        return

    subscribe(_handle_event)
    logger.info("Rule engine loaded")
    _loaded = True


__all__ = ["load_rules", "evaluate", "run_action", "available_actions"]
