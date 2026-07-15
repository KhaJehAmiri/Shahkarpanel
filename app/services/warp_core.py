"""Helpers for WARP credential lifecycle (node refs + cleanup)."""
from __future__ import annotations

from typing import Optional, Sequence

from app.db import Session
from app.db import models as db_models


def clear_node_warp_refs(db: Session, tags: Optional[Sequence[str]] = None) -> list[int]:
    """Disable per-node WARP when referenced account tag(s) disappear.

    Returns node ids that were changed (caller may restart them).
    """
    q = db.query(db_models.Node).filter(db_models.Node.warp_enabled.is_(True))
    if tags is not None:
        tag_set = {str(t) for t in tags if t}
        if not tag_set:
            return []
        q = q.filter(db_models.Node.warp_tag.in_(tag_set))
    nodes = q.all()
    ids = [n.id for n in nodes]
    for node in nodes:
        node.warp_enabled = False
    if nodes:
        db.commit()
    return ids
