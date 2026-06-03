"""Workflow engine.

A workflow is a named, event-triggered sequence of actions (a superset of a
single rule). It reuses the rule-engine condition evaluator and action registry
so any action available to rules is available to workflow steps. Gated behind
the ``workflows`` feature flag.

Each step is ``{"action": <name>, "params": {...}}`` and steps run in order;
a failing step is logged and the workflow continues with the next step.
"""
import logging

from app import feature_flags
from app.events import Event, subscribe
from app.rules.actions import run_action
from app.rules.conditions import evaluate

logger = logging.getLogger("uvicorn.error")

_loaded = False


def _handle_event(event: Event) -> None:
    from app.db import GetDB
    from app.db.models import Workflow

    with GetDB() as db:
        rows = (
            db.query(Workflow)
            .filter(Workflow.enabled.is_(True), Workflow.trigger_event == event.type.value)
            .all()
        )
        workflows = [(w.name, w.condition, list(w.steps or [])) for w in rows]

    for name, condition, steps in workflows:
        try:
            if not evaluate(condition, event.payload):
                continue
        except Exception:
            logger.exception("Workflow '%s' condition failed", name)
            continue

        for index, step in enumerate(steps):
            action = step.get("action")
            params = step.get("params") or {}
            try:
                run_action(action, params, event)
            except Exception:
                logger.exception("Workflow '%s' step %d (%s) failed", name, index, action)


def load_workflows() -> None:
    """Wire the workflow engine to the event bus. Safe to call more than once."""
    global _loaded
    if _loaded:
        return

    if not feature_flags.is_enabled("workflows"):
        logger.info("Workflow engine disabled (feature flag 'workflows' is off)")
        _loaded = True
        return

    subscribe(_handle_event)
    logger.info("Workflow engine loaded")
    _loaded = True


__all__ = ["load_workflows"]
