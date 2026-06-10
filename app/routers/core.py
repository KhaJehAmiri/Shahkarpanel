import asyncio
import json
import time

import commentjson
from fastapi import APIRouter, Body, Depends, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from app import xray
from app.db import Session, get_db
from app.models.admin import Admin
from app.models.core import CoreStats
from app.utils import responses, warp
from app.utils.outbound_test import test_outbound
from app.utils.ws_auth import ws_bearer_token
from app.xray import XRayConfig
from config import XRAY_JSON

router = APIRouter(tags=["Core"], prefix="/api", responses={401: responses._401})


@router.websocket("/core/logs")
async def core_logs(websocket: WebSocket, db: Session = Depends(get_db)):
    token = ws_bearer_token(websocket)
    admin = Admin.get_admin(token, db)
    if not admin:
        return await websocket.close(reason="Unauthorized", code=4401)

    if not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    interval = websocket.query_params.get("interval")
    if interval:
        try:
            interval = float(interval)
        except ValueError:
            return await websocket.close(reason="Invalid interval value", code=4400)
        if interval > 10:
            return await websocket.close(
                reason="Interval must be more than 0 and at most 10 seconds", code=4400
            )

    await websocket.accept()

    cache = ""
    last_sent_ts = 0
    with xray.core.get_logs() as logs:
        while True:
            if interval and time.time() - last_sent_ts >= interval and cache:
                try:
                    await websocket.send_text(cache)
                except (WebSocketDisconnect, RuntimeError):
                    break
                cache = ""
                last_sent_ts = time.time()

            if not logs:
                try:
                    await asyncio.wait_for(websocket.receive(), timeout=0.2)
                    continue
                except asyncio.TimeoutError:
                    continue
                except (WebSocketDisconnect, RuntimeError):
                    break

            log = logs.popleft()

            if interval:
                cache += f"{log}\n"
                continue

            try:
                await websocket.send_text(log)
            except (WebSocketDisconnect, RuntimeError):
                break


@router.get("/core", response_model=CoreStats)
def get_core_stats(admin: Admin = Depends(Admin.get_current)):
    """Retrieve core statistics such as version and uptime."""
    return CoreStats(
        version=xray.core.version,
        started=xray.core.started,
        logs_websocket=router.url_path_for("core_logs"),
    )


@router.post("/core/restart", responses={403: responses._403})
def restart_core(admin: Admin = Depends(Admin.check_sudo_admin)):
    """Restart the core and all connected nodes."""
    startup_config = xray.config.include_db_users()
    xray.core.restart(startup_config)

    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)

    return {}


@router.get("/core/config", responses={403: responses._403})
def get_core_config(admin: Admin = Depends(Admin.check_sudo_admin)) -> dict:
    """Get the current core configuration."""
    with open(XRAY_JSON, "r") as f:
        config = commentjson.loads(f.read())

    return config


@router.put("/core/config", responses={403: responses._403})
def modify_core_config(
    payload: dict, admin: Admin = Depends(Admin.check_sudo_admin)
) -> dict:
    """Modify the core configuration and restart the core."""
    try:
        config = XRayConfig(payload, api_port=xray.config.api_port)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    xray.config = config
    with open(XRAY_JSON, "w") as f:
        f.write(json.dumps(payload, indent=4))

    startup_config = xray.config.include_db_users()
    xray.core.restart(startup_config)
    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)

    xray.hosts.update()

    return payload


@router.get("/core/warp", responses={403: responses._403})
def get_warp_account(admin: Admin = Depends(Admin.check_sudo_admin)) -> dict:
    """Return the registered Cloudflare WARP account, if any."""
    data = warp.get_warp()
    if not data:
        return {"registered": False}
    return data


@router.post("/core/warp/register", responses={403: responses._403})
def register_warp_account(
    payload: dict = Body(default={}),
    admin: Admin = Depends(Admin.check_sudo_admin),
) -> dict:
    """Register a fresh Cloudflare WARP device and return a ready outbound."""
    tag = (payload or {}).get("tag") or "warp"
    try:
        return warp.register_warp(tag=tag)
    except warp.WarpError as err:
        raise HTTPException(status_code=502, detail=str(err))


@router.post("/core/warp/license", responses={403: responses._403})
def set_warp_license(
    payload: dict = Body(...),
    admin: Admin = Depends(Admin.check_sudo_admin),
) -> dict:
    """Apply a WARP+ license key to the registered device."""
    license_key = (payload or {}).get("license", "").strip()
    if not license_key:
        raise HTTPException(status_code=400, detail="license is required")
    try:
        return warp.set_warp_license(license_key)
    except warp.WarpError as err:
        raise HTTPException(status_code=502, detail=str(err))


@router.delete("/core/warp", responses={403: responses._403})
def delete_warp_account(admin: Admin = Depends(Admin.check_sudo_admin)) -> dict:
    """Forget the locally stored WARP credentials."""
    warp.delete_warp_data()
    return {"registered": False}


@router.post("/core/outbounds/test", responses={403: responses._403})
def test_core_outbound(
    payload: dict = Body(...),
    admin: Admin = Depends(Admin.check_sudo_admin),
) -> dict:
    """Measure latency through an outbound (TCP dial or HTTP burstObservatory probe)."""
    outbound = payload.get("outbound")
    if not isinstance(outbound, dict):
        raise HTTPException(status_code=400, detail="outbound is required")

    all_outbounds = payload.get("allOutbounds") or []
    if not isinstance(all_outbounds, list):
        all_outbounds = []

    test_url = str(payload.get("testURL") or "")
    mode = str(payload.get("mode") or "")
    result = test_outbound(outbound, all_outbounds, test_url=test_url, mode=mode)
    return result.to_dict()
