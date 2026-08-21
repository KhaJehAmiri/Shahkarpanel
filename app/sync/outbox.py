"""Durable fleet-apply queue (phase 2).

API commits user rows then inserts here in the same session. Worker claims
with SKIP LOCKED, applies via existing hot paths, and records retry/backoff.
Live inbound ACK is required before ``done`` / ``users.sync_state=live``.
"""
from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("uvicorn.error")

ACTIONS = frozenset({"add", "disable", "delete", "quota_cap", "protocol_change"})
MAX_ATTEMPTS = 20
BATCH = 12
STALE_RUNNING_SEC = 45
_drain_lock = threading.Lock()


def snapshot_user(dbuser) -> dict[str, Any]:
    """Enough to replay add/disable/delete after the ORM row is gone."""
    uid = int(getattr(dbuser, "id", 0) or 0)
    username = str(getattr(dbuser, "username", "") or "")
    status = getattr(dbuser, "status", None)
    status_s = getattr(status, "value", status)
    pubkey = None
    slot = None
    proxies: list[dict[str, Any]] = []
    for proxy in getattr(dbuser, "proxies", None) or []:
        ptype = getattr(proxy, "type", None)
        type_s = str(getattr(ptype, "value", ptype) or "")
        settings = dict(getattr(proxy, "settings", None) or {})
        slim = {
            k: settings[k]
            for k in ("id", "password", "method", "public_key", "private_key", "address", "uuid")
            if k in settings and settings[k] is not None
        }
        proxies.append({"type": type_s, "settings": slim})
        if type_s in ("WireGuard", "wireguard"):
            pubkey = settings.get("public_key") or pubkey
            try:
                from app.wireguard.finalmask_shard import user_finalmask_slot

                slot = user_finalmask_slot(settings)
            except Exception:
                slot = settings.get("finalmask_slot", slot)
    return {
        "user_id": uid,
        "username": username,
        "email": f"{uid}.{username}" if uid and username else username,
        "status": str(status_s or ""),
        "public_key": pubkey,
        "slot": slot,
        "proxies": proxies,
    }


def _set_user_sync(
    db: Session,
    user_id: Optional[int],
    state: str,
    *,
    error: Optional[str] = None,
    acked: bool = False,
) -> None:
    if not user_id:
        return
    from app.db.models import User

    dbuser = db.query(User).filter(User.id == int(user_id)).first()
    if dbuser is None:
        return
    dbuser.sync_state = state
    dbuser.sync_error = (error or "")[:2000] or None
    if acked:
        dbuser.sync_acked_at = datetime.utcnow()


def enqueue(
    db: Session,
    *,
    user_id: Optional[int],
    action: str,
    target: str = "all",
    node_id: Optional[int] = None,
    shard_or_tag: Optional[str] = None,
    payload: Optional[dict] = None,
    commit: bool = True,
) -> Optional[int]:
    """Insert a pending row. Duplicate pending/running is coalesced (no error)."""
    action = (action or "").strip()
    if action not in ACTIONS:
        raise ValueError(f"unknown outbox action {action}")
    target = (target or "all").strip() or "all"
    from app.db.models import UserSyncOutbox

    uid = int(user_id) if user_id else None
    nid = int(node_id) if node_id is not None else None
    q = db.query(UserSyncOutbox).filter(
        UserSyncOutbox.user_id == uid,
        UserSyncOutbox.action == action,
        UserSyncOutbox.target == target,
        UserSyncOutbox.status.in_(("pending", "running")),
    )
    if nid is None:
        q = q.filter(UserSyncOutbox.node_id.is_(None))
    else:
        q = q.filter(UserSyncOutbox.node_id == nid)
    existing = q.first()
    if existing is not None:
        if payload:
            existing.payload = payload
            existing.updated_at = datetime.utcnow()
        _set_user_sync(db, uid, "pending")
        if commit:
            db.commit()
        return int(existing.id)

    now = datetime.utcnow()
    row = UserSyncOutbox(
        user_id=uid,
        action=action,
        target=target,
        node_id=nid,
        shard_or_tag=shard_or_tag,
        payload=payload or {},
        status="pending",
        attempts=0,
        next_retry_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _set_user_sync(db, uid, "pending")
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return int(row.id)


def schedule_user_sync(
    db: Session,
    dbuser,
    action: str,
    *,
    target: str = "all",
    payload: Optional[dict] = None,
    commit: bool = True,
) -> Optional[int]:
    snap = payload if payload is not None else snapshot_user(dbuser)
    oid = enqueue(
        db,
        user_id=getattr(dbuser, "id", None),
        action=action,
        target=target,
        payload=snap,
        commit=commit,
    )
    _wake()
    return oid


def schedule_user_sync_by_id(
    user_id: Optional[int],
    action: str,
    *,
    payload: Optional[dict] = None,
) -> Optional[int]:
    if not user_id and not payload:
        return None
    from app.db import GetDB, crud

    with GetDB() as db:
        dbuser = crud.get_user_by_id(db, int(user_id)) if user_id else None
        if dbuser is not None:
            return schedule_user_sync(db, dbuser, action, payload=payload)
        oid = enqueue(
            db,
            user_id=user_id,
            action=action,
            payload=payload or {},
            commit=True,
        )
        _wake()
        return oid


def _wake() -> None:
    try:
        from app.sync.wake import notify_worker

        notify_worker("outbox")
    except Exception:
        logger.debug("outbox wake failed", exc_info=True)


def _backoff(attempts: int) -> datetime:
    cap = min(300, 2 ** max(1, int(attempts)))
    jitter = random.uniform(0, min(8.0, cap * 0.2))
    return datetime.utcnow() + timedelta(seconds=cap + jitter)


def _reclaim_stale(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=STALE_RUNNING_SEC)
    from app.db.models import UserSyncOutbox

    n = (
        db.query(UserSyncOutbox)
        .filter(
            UserSyncOutbox.status == "running",
            UserSyncOutbox.updated_at < cutoff,
        )
        .update(
            {
                UserSyncOutbox.status: "pending",
                UserSyncOutbox.updated_at: datetime.utcnow(),
                UserSyncOutbox.next_retry_at: datetime.utcnow(),
            },
            synchronize_session=False,
        )
    )
    if n:
        db.commit()
    return int(n or 0)


def _claim_postgres(db: Session, limit: int) -> list[int]:
    rows = db.execute(
        text(
            """
            UPDATE user_sync_outbox AS o
            SET status = 'running',
                attempts = o.attempts + 1,
                updated_at = (NOW() AT TIME ZONE 'utc')
            WHERE o.id IN (
                SELECT id FROM user_sync_outbox
                WHERE status IN ('pending', 'failed')
                  AND (next_retry_at IS NULL OR next_retry_at <= (NOW() AT TIME ZONE 'utc'))
                  AND attempts < :max_attempts
                ORDER BY CASE WHEN action IN ('disable', 'delete') THEN 0 ELSE 1 END, id
                FOR UPDATE SKIP LOCKED
                LIMIT :lim
            )
            RETURNING o.id
            """
        ),
        {"lim": int(limit), "max_attempts": MAX_ATTEMPTS},
    ).fetchall()
    db.commit()
    return [int(r[0]) for r in rows]


def _claim_generic(db: Session, limit: int) -> list[int]:
    from app.db.models import UserSyncOutbox

    now = datetime.utcnow()
    from sqlalchemy import case

    rows = (
        db.query(UserSyncOutbox)
        .filter(
            UserSyncOutbox.status.in_(("pending", "failed")),
            (UserSyncOutbox.next_retry_at.is_(None))
            | (UserSyncOutbox.next_retry_at <= now),
            UserSyncOutbox.attempts < MAX_ATTEMPTS,
        )
        .order_by(
            case(
                (UserSyncOutbox.action.in_(("disable", "delete")), 0),
                else_=1,
            ),
            UserSyncOutbox.id,
        )
        .limit(int(limit))
        .all()
    )
    ids = []
    for row in rows:
        row.status = "running"
        row.attempts = int(row.attempts or 0) + 1
        row.updated_at = now
        ids.append(int(row.id))
    if ids:
        db.commit()
    return ids


def _apply_row(row) -> None:
    action = row.action
    payload = dict(row.payload or {})
    user_id = row.user_id or payload.get("user_id")
    from app.sync.hot_apply import apply_action
    from app.sync.ack import confirm_action

    apply_action(action, user_id=user_id, payload=payload)
    confirm_action(action, user_id=user_id, payload=payload)


def _finish(row_id: int, *, ok: bool, error: Optional[str] = None) -> None:
    from app.db import GetDB
    from app.db.models import UserSyncOutbox

    with GetDB() as db:
        row = db.query(UserSyncOutbox).filter(UserSyncOutbox.id == int(row_id)).first()
        if row is None:
            return
        now = datetime.utcnow()
        row.updated_at = now
        if ok:
            row.status = "done"
            row.acked_at = now
            row.last_error = None
            _set_user_sync(db, row.user_id, "live", acked=True)
            sync_state = "live"
        else:
            row.last_error = (error or "apply failed")[:2000]
            if int(row.attempts or 0) >= MAX_ATTEMPTS:
                row.status = "dead"
                _set_user_sync(db, row.user_id, "dead", error=row.last_error)
                sync_state = "dead"
            else:
                row.status = "failed"
                row.next_retry_at = _backoff(int(row.attempts or 1))
                _set_user_sync(db, row.user_id, "failed", error=row.last_error)
                sync_state = "failed"
        username = None
        payload = dict(row.payload or {})
        username = payload.get("username")
        user_id = row.user_id
        db.commit()
    try:
        from app.sync.live import publish_event

        publish_event(
            "user.sync",
            {
                "user_id": user_id,
                "username": username,
                "sync_state": sync_state,
            },
        )
    except Exception:
        pass


def drain(*, limit: int = BATCH) -> int:
    """Claim and apply due outbox rows. Safe to call from wake + interval job."""
    if not _drain_lock.acquire(blocking=False):
        return 0
    applied = 0
    try:
        from app.db import GetDB

        with GetDB() as db:
            _reclaim_stale(db)
            dialect = db.bind.dialect.name if db.bind is not None else ""
            if dialect == "postgresql":
                ids = _claim_postgres(db, limit)
            else:
                ids = _claim_generic(db, limit)
        if not ids:
            return 0
        from app.db.models import UserSyncOutbox

        for row_id in ids:
            with GetDB() as db:
                row = (
                    db.query(UserSyncOutbox)
                    .filter(UserSyncOutbox.id == int(row_id))
                    .first()
                )
                if row is None:
                    continue
                # Detach values; apply must not hold this session during RPC.
                action = row.action
                payload = dict(row.payload or {})
                user_id = row.user_id
            try:
                class _Row:
                    pass

                claimed = _Row()
                claimed.action = action
                claimed.payload = payload
                claimed.user_id = user_id
                _apply_row(claimed)
                _finish(row_id, ok=True)
                applied += 1
            except Exception as exc:
                logger.exception("outbox apply failed id=%s action=%s", row_id, action)
                _finish(row_id, ok=False, error=str(exc))
        if applied >= int(limit):
            # More rows likely remain; don't wait for the 2s interval job.
            _wake()
        return applied
    finally:
        _drain_lock.release()
