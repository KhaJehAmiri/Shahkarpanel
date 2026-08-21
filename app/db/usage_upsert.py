"""Batched hourly usage writes.

The old path did ``SELECT all user_ids in this hour`` plus an executemany
UPDATE per transferring user, per node, every 15s. At tens of thousands of
users that pins PostgreSQL and starves the panel API pool until Docker restart.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Sequence

from sqlalchemy.orm import Session

from app.db.models import NodeUserProtocolUsage, NodeUserUsage


_CHUNK = 400


def _chunked(rows: Sequence[dict], size: int = _CHUNK) -> Iterable[List[dict]]:
    for i in range(0, len(rows), size):
        yield list(rows[i : i + size])


def _coalesce_rows(rows: Sequence[dict], conflict_cols: Sequence[str]) -> List[dict]:
    """Merge duplicate conflict keys in one INSERT batch.

    Postgres rejects ``ON CONFLICT DO UPDATE`` when the same constrained key
    appears twice in a single VALUES list (``cannot affect row a second time``).
    Usage collectors often emit the same ``(user, node[, protocol])`` twice in
    one tick (Xray + Finalmask / multi-inbound), so sum traffic here first.
    """
    merged: dict = {}
    for row in rows:
        key = tuple(row[c] for c in conflict_cols)
        prev = merged.get(key)
        if prev is None:
            merged[key] = dict(row)
            continue
        prev["used_traffic"] = int(prev.get("used_traffic") or 0) + int(
            row.get("used_traffic") or 0
        )
    return list(merged.values())


def _pg_upsert(db: Session, table, rows: Sequence[dict], conflict_cols: Sequence[str]) -> bool:
    if not rows:
        return True
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
    except Exception:
        return False
    rows = _coalesce_rows(rows, conflict_cols)
    for chunk in _chunked(rows):
        stmt = pg_insert(table).values(list(chunk))
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_cols),
            set_={"used_traffic": table.c.used_traffic + stmt.excluded.used_traffic},
        )
        db.execute(stmt)
    db.commit()
    return True


def upsert_node_user_usage(
    db: Session,
    params: list,
    node_id,
    created_at: datetime,
    consumption_factor: float = 1,
) -> None:
    rows = [
        {
            "user_id": int(p["uid"]),
            "node_id": node_id,
            "created_at": created_at,
            "used_traffic": int(int(p["value"]) * consumption_factor),
        }
        for p in params
        if p.get("uid") is not None and int(p.get("value") or 0) > 0
    ]
    if not rows:
        return
    if node_id is None:
        raise RuntimeError("null node_id cannot use postgres ON CONFLICT")
    if db.bind.dialect.name == "postgresql" and _pg_upsert(
        db,
        NodeUserUsage.__table__,
        rows,
        ("created_at", "user_id", "node_id"),
    ):
        return
    raise RuntimeError("non-postgresql usage upsert is handled by caller")


def upsert_protocol_usage(
    db: Session,
    params: list,
    node_id,
    created_at: datetime,
    protocol: str,
    consumption_factor: float = 1,
) -> None:
    proto = str(protocol)[:32]
    rows = [
        {
            "user_id": int(p["uid"]),
            "node_id": node_id,
            "created_at": created_at,
            "protocol": proto,
            "used_traffic": int(int(p["value"]) * consumption_factor),
        }
        for p in params
        if p.get("uid") is not None and int(p.get("value") or 0) > 0
    ]
    if not rows:
        return
    if node_id is None:
        raise RuntimeError("null node_id cannot use postgres ON CONFLICT")
    if db.bind.dialect.name == "postgresql" and _pg_upsert(
        db,
        NodeUserProtocolUsage.__table__,
        rows,
        ("created_at", "user_id", "node_id", "protocol"),
    ):
        return
    raise RuntimeError("non-postgresql usage upsert is handled by caller")
