"""Live dashboard WebSocket — Redis fan-in, no fleet RPC (phase 6)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.db import GetDB, Session, crud, get_db
from app.models.admin import Admin
from app.sync.live import load_snapshot, scope_snapshot, snapshot_fresh
from app.utils import responses
from app.utils.ws_auth import ws_bearer_token

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["Live"], prefix="/api", responses={401: responses._401})

_PING_SEC = 20.0


def _scope_admin(admin: Admin, db: Session) -> tuple[bool, Optional[int], Optional[int]]:
    if admin.is_sudo:
        return True, None, None
    dbadmin = crud.get_admin(db, admin.username)
    return (
        False,
        int(dbadmin.id) if dbadmin is not None else None,
        int(dbadmin.tenant_id) if dbadmin is not None and dbadmin.tenant_id is not None else None,
    )


def _scoped(
    snap: dict | None,
    *,
    is_sudo: bool,
    admin_id: Optional[int],
    tenant_id: Optional[int],
) -> dict | None:
    if not snap:
        return None
    return scope_snapshot(
        snap, is_sudo=is_sudo, admin_id=admin_id, tenant_id=tenant_id
    )


@router.get("/live/snapshot")
def live_snapshot(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Current KPI tick from Redis. HTTP fallback when WebSocket is down."""
    is_sudo, admin_id, tenant_id = _scope_admin(admin, db)
    snap = load_snapshot()
    scoped = _scoped(snap, is_sudo=is_sudo, admin_id=admin_id, tenant_id=tenant_id)
    if not scoped or not snapshot_fresh(snap):
        return {"kind": "empty", "fresh": False}
    scoped["fresh"] = True
    return scoped


@router.websocket("/live")
async def live_ws(websocket: WebSocket):
    token = ws_bearer_token(websocket)
    with GetDB() as db:
        admin = Admin.get_admin(token, db)
        if not admin:
            admin = None
            is_sudo, admin_id, tenant_id = True, None, None
        else:
            is_sudo, admin_id, tenant_id = _scope_admin(admin, db)
    if not admin:
        return await websocket.close(reason="Unauthorized", code=4401)

    await websocket.accept()
    scoped = _scoped(
        load_snapshot(), is_sudo=is_sudo, admin_id=admin_id, tenant_id=tenant_id
    )
    if scoped:
        try:
            await websocket.send_json(scoped)
        except (WebSocketDisconnect, RuntimeError):
            return

    queue: asyncio.Queue = asyncio.Queue()

    async def redis_pump() -> None:
        from config import REDIS_URL

        if not REDIS_URL:
            return
        client = None
        pubsub = None
        try:
            import redis.asyncio as aioredis

            from app.sync.live import LIVE_CHANNEL

            client = aioredis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=None,
                health_check_interval=15,
            )
            pubsub = client.pubsub()
            await pubsub.subscribe(LIVE_CHANNEL)
            async for msg in pubsub.listen():
                if msg is None:
                    continue
                if msg.get("type") != "message":
                    continue
                await queue.put(("msg", msg.get("data")))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("live ws redis listen ended", exc_info=True)
        finally:
            try:
                if pubsub is not None:
                    await pubsub.unsubscribe(LIVE_CHANNEL)
                    await pubsub.aclose()
            except Exception:
                pass
            try:
                if client is not None:
                    await client.aclose()
            except Exception:
                pass
            try:
                await queue.put(("redis_done", None))
            except Exception:
                pass

    async def client_pump() -> None:
        try:
            while True:
                await websocket.receive()
        except (WebSocketDisconnect, RuntimeError):
            await queue.put(("bye", None))
        except asyncio.CancelledError:
            raise

    async def ping_pump() -> None:
        try:
            while True:
                await asyncio.sleep(_PING_SEC)
                await queue.put(("ping", None))
        except asyncio.CancelledError:
            raise

    tasks = [
        asyncio.create_task(redis_pump()),
        asyncio.create_task(client_pump()),
        asyncio.create_task(ping_pump()),
    ]
    try:
        while True:
            kind, data = await queue.get()
            if kind == "bye":
                break
            if kind == "redis_done":
                try:
                    await websocket.close(code=1011)
                except Exception:
                    pass
                break
            try:
                if kind == "ping":
                    await websocket.send_json({"kind": "ping"})
                    continue
                raw = data
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                if not isinstance(raw, str):
                    continue
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("kind") == "tick":
                    payload = scope_snapshot(
                        payload,
                        is_sudo=is_sudo,
                        admin_id=admin_id,
                        tenant_id=tenant_id,
                    )
                await websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                break
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
