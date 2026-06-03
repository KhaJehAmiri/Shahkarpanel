"""Safe, declarative condition evaluation for the rule engine.

Conditions are plain JSON (no code execution). Grammar::

    condition := None                       # always true
               | {"all": [condition, ...]}  # logical AND
               | {"any": [condition, ...]}  # logical OR
               | {"not": condition}         # negation
               | {"field": str, "op": str, "value": any}   # leaf comparison

``field`` may be a dotted path into the event payload, e.g. "user.status".
"""
from typing import Any, Optional

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and a > b,
    "ge": lambda a, b: a is not None and a >= b,
    "lt": lambda a, b: a is not None and a < b,
    "le": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in b if b is not None else False,
    "contains": lambda a, b: b in a if a is not None else False,
}


def _resolve(payload: dict, path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def evaluate(condition: Optional[dict], payload: dict) -> bool:
    if not condition:
        return True

    if "all" in condition:
        return all(evaluate(sub, payload) for sub in condition["all"])
    if "any" in condition:
        return any(evaluate(sub, payload) for sub in condition["any"])
    if "not" in condition:
        return not evaluate(condition["not"], payload)

    field = condition.get("field")
    op = condition.get("op")
    expected = condition.get("value")
    if field is None or op not in _OPS:
        return False

    actual = _resolve(payload, field)
    try:
        return bool(_OPS[op](actual, expected))
    except TypeError:
        return False
