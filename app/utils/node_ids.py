"""Parse host node_ids (JSON array or comma-separated ints)."""
from __future__ import annotations

import json
from typing import List, Optional


def parse_node_ids(raw: Optional[str]) -> Optional[List[int]]:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [int(x) for x in parsed]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    out: List[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out or None


def host_visible_on_node(node_ids_raw: Optional[str], node_id: Optional[int]) -> bool:
    """Return True when a host should appear for ``node_id`` (None = panel core)."""
    allowed = parse_node_ids(node_ids_raw)
    if not allowed:
        return True
    key = 0 if node_id is None else int(node_id)
    return key in allowed
