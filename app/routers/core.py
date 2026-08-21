import asyncio
import json
import subprocess
import time

import commentjson
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, UploadFile, WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from app import logger, xray
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.models.core import CoreStats
from app.rbac import require_permission

_core_read = Depends(require_permission("core:read"))
_core_write = Depends(require_permission("core:write"))
from app.utils import responses, warp
from app.utils.outbound_test import test_outbound
from app.utils.ws_auth import ws_bearer_token
from app.xray import XRayConfig
from app.xray.inbound_normalize import (
    inbound_is_enabled,
    normalize_core_config_payload,
    runtime_core_config,
)
from app.xray.inbound_ports import collect_port_issues, format_port_issues
from config import XRAY_ASSETS_PATH, XRAY_EXECUTABLE_PATH, XRAY_JSON

router = APIRouter(tags=["Core"], prefix="/api", responses={401: responses._401})


def _xray_config_test_error(config_dict: dict) -> str | None:
    """Return a short error message when ``xray run -test`` rejects the config."""
    import subprocess

    try:
        proc = subprocess.run(
            [XRAY_EXECUTABLE_PATH, "run", "-test", "-config", "stdin:"],
            input=json.dumps(config_dict),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return str(exc)
    if proc.returncode == 0:
        return None
    text = (proc.stderr or proc.stdout or "").strip()
    if not text:
        return "Xray rejected the configuration"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else "Xray rejected the configuration"


def _validate_inbound_ports_or_raise(inbounds: list) -> None:
    issues = collect_port_issues(inbounds)
    if issues:
        raise HTTPException(status_code=400, detail=format_port_issues(issues))


@router.websocket("/core/logs")
async def core_logs(websocket: WebSocket, db: Session = Depends(get_db)):
    token = ws_bearer_token(websocket)
    admin = Admin.get_admin(token, db)
    if not admin:
        return await websocket.close(reason="Unauthorized", code=4401)

    from app.rbac import has_permission

    if not has_permission(admin, "core:read"):
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
def get_core_stats(admin: Admin = _core_read):
    """Retrieve core statistics such as version and uptime."""
    started = bool(xray.core.started)
    version = xray.core.version
    startup_error = xray.core.startup_error if not started else None
    failed_inbound_tag = xray.core.failed_inbound_tag if not started else None
    failed_port = xray.core.failed_port if not started else None
    try:
        from app.runtime_role import owns_control_plane
        from app.sync.live import load_snapshot, snapshot_fresh

        if not owns_control_plane():
            snap = load_snapshot()
            snap_started = bool(snap.get("xray_started")) if snap else False
            # Never treat a stale snapshot as "stopped" — that made the Core
            # banner flash stopped while the worker's Xray was still running.
            if snap_started or (snap is not None and snapshot_fresh(snap)):
                started = snap_started
                version = (snap.get("xray_version") if snap else None) or version
                if started:
                    startup_error = None
                    failed_inbound_tag = None
                    failed_port = None
            if not started:
                from app.xray.core import find_stdin_xray_pids

                if find_stdin_xray_pids(XRAY_EXECUTABLE_PATH):
                    started = True
                    startup_error = None
                    failed_inbound_tag = None
                    failed_port = None
    except Exception:
        pass
    return CoreStats(
        version=version,
        started=started,
        logs_websocket=router.url_path_for("core_logs"),
        startup_error=startup_error,
        failed_inbound_tag=failed_inbound_tag,
        failed_port=failed_port,
    )


@router.post("/core/validate-inbounds", responses={403: responses._403, 400: responses._400})
def validate_inbounds(payload: dict, admin: Admin = _core_write) -> dict:
    """Check inbound ports for duplicates and conflicts with panel services."""
    inbounds = [
        ib
        for ib in list(payload.get("inbounds") or [])
        if isinstance(ib, dict) and inbound_is_enabled(ib)
    ]
    _validate_inbound_ports_or_raise(inbounds)
    return {"ok": True}


@router.post("/core/restart", responses={403: responses._403})
def restart_core(admin: Admin = _core_write):
    """Restart the panel Xray core. Node fleet is not restarted from HTTP."""
    from app.runtime_role import delegate_to_worker

    if delegate_to_worker("restart_core"):
        return {}
    startup_config = xray.config.include_db_users()
    xray.core.restart(startup_config, force=True)

    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)

    return {}


@router.get("/core/egress-guard", responses={403: responses._403})
def get_egress_guard(_: Admin = Depends(require_permission("core:read"))):
    """Fleet egress-guard status (BitTorrent / malware / piracy blocks)."""
    from app import platform_settings as ps
    from app.egress_guard import RULE_MARK, build_egress_guard_rules, is_enabled

    enabled = is_enabled()
    rules = build_egress_guard_rules() if enabled else []
    return {
        "enabled": enabled,
        "rule_mark": RULE_MARK,
        "rule_count": len(rules),
        "setting_key": "security.egress_guard_enabled",
        "platform_value": ps.get_bool("security.egress_guard_enabled", True),
    }


class EgressGuardUpdate(BaseModel):
    enabled: bool
    apply_now: bool = True


@router.put("/core/egress-guard", responses={403: responses._403})
def put_egress_guard(body: EgressGuardUpdate, admin: Admin = _core_write):
    """Enable/disable fleet egress guard and optionally rebuild+push configs."""
    from app import platform_settings as ps

    ps.set_setting("security.egress_guard_enabled", bool(body.enabled))
    applied = False
    if body.apply_now:
        startup_config = xray.config.include_db_users()
        if xray.core.started:
            xray.core.restart(startup_config, force=True)
        for node_id, node in list(xray.nodes.items()):
            if node.connected:
                xray.operations.restart_node(node_id, startup_config)
        applied = True
    return {"enabled": bool(body.enabled), "applied": applied}


@router.post("/core/egress-guard/apply", responses={403: responses._403})
def apply_egress_guard(admin: Admin = _core_write):
    """Rebuild panel+node Xray configs so egress-guard rules are live."""
    from app.egress_guard import RULE_MARK, is_enabled

    startup_config = xray.config.include_db_users()
    if xray.core.started:
        xray.core.restart(startup_config, force=True)
    nodes = 0
    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)
            nodes += 1
    live_rules = 0
    try:
        routing = startup_config.get("routing") or {}
        rules = routing.get("rules") or []
        live_rules = sum(1 for r in rules if isinstance(r, dict) and r.get(RULE_MARK))
    except Exception:
        live_rules = 0
    return {
        "enabled": is_enabled(),
        "nodes_restarted": nodes,
        "egress_rules": live_rules,
    }


@router.post("/core/start", responses={403: responses._403})
def start_core(admin: Admin = _core_write):
    """Start the panel Xray core if it is stopped."""
    from app.runtime_role import delegate_to_worker

    if delegate_to_worker("start_core"):
        return {"started": True}
    if xray.core.started:
        return {"started": True}
    startup_config = xray.config.include_db_users()
    xray.core.start(startup_config)
    return {"started": xray.core.started}


@router.post("/core/stop", responses={403: responses._403})
def stop_core(admin: Admin = _core_write):
    """Stop the panel Xray core."""
    from app.runtime_role import delegate_to_worker

    if delegate_to_worker("stop_core"):
        return {"started": False}
    if xray.core.started:
        xray.core.stop()
    return {"started": xray.core.started}


@router.get("/core/config", responses={403: responses._403})
def get_core_config(admin: Admin = Depends(require_permission("core:read"))) -> dict:
    """Get the current core configuration."""
    with open(XRAY_JSON, "r") as f:
        config = commentjson.loads(f.read())

    return config


@router.put("/core/config", responses={403: responses._403})
def modify_core_config(
    payload: dict,
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Modify the core configuration and restart the core."""
    from app.services.edge_proxy import apply_edge_runtime_to_config, sync_edge_nginx

    payload = normalize_core_config_payload(payload)
    payload["inbounds"] = list(payload.get("inbounds") or [])
    # Persist full payload (including disabled inbounds); start core from runtime only.
    runtime_payload = runtime_core_config(payload)
    try:
        config = XRayConfig(runtime_payload, api_port=xray.config.api_port)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    try:
        startup_config = config.include_db_users()
    except Exception as err:
        logger.exception("Failed to merge DB users into Xray config")
        raise HTTPException(status_code=500, detail=f"Failed to merge users: {err}") from err

    runtime_config = apply_edge_runtime_to_config(startup_config)
    _validate_inbound_ports_or_raise(list(runtime_config.get("inbounds") or []))
    test_err = _xray_config_test_error(dict(runtime_config))
    if test_err:
        raise HTTPException(status_code=400, detail=test_err)

    from app.xray import config_history

    # Snapshot the current config before overwriting so a bad change (that still
    # passes `xray run -test`) can be rolled back.
    previous_raw = None
    try:
        with open(XRAY_JSON, "r", encoding="utf-8") as f:
            previous_raw = f.read()
    except OSError:
        previous_raw = None
    if previous_raw:
        config_history.snapshot_config(previous_raw)

    prev_config = xray.config
    prev_startup = prev_config.include_db_users()

    try:
        with open(XRAY_JSON, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=4))
    except OSError as err:
        logger.exception("Failed to write Xray config to %s", XRAY_JSON)
        raise HTTPException(
            status_code=500,
            detail=f"Cannot write Xray config ({XRAY_JSON}): {err}",
        ) from err

    xray.config = config

    from app.xray.config_apply import can_hot_apply_core_config, inbounds_structure_changed
    from app.xray.serving import hot_sync_main_core

    structure_changed = inbounds_structure_changed(prev_startup, startup_config)

    applied_without_restart = False
    if can_hot_apply_core_config(prev_startup, startup_config):
        if hot_sync_main_core():
            applied_without_restart = True
            logger.info(
                "Core config saved without restart (inbound structure unchanged; sessions preserved)"
            )
        else:
            logger.info("Hot apply after config save failed; falling back to full core restart")

    if not applied_without_restart:
        try:
            xray.core.restart(startup_config)
        except Exception as exc:
            # The new config passed `xray run -test` but the live core still failed
            # to start (e.g. a runtime bind conflict). Roll back so the panel core
            # never stays down because of a bad save.
            logger.exception("Xray restart failed after config save; rolling back")
            xray.config = prev_config
            if previous_raw:
                config_history.restore_config_file(previous_raw, XRAY_JSON)
                try:
                    xray.core.restart(prev_config.include_db_users())
                except Exception:
                    logger.exception("Rollback: failed to restart core with previous config")
            raise HTTPException(
                status_code=400,
                detail=(
                    "Xray failed to start with the new config; rolled back to the "
                    f"previous config. ({exc})"
                ),
            ) from exc

        for node_id, node in list(xray.nodes.items()):
            if node.connected:
                xray.operations.restart_node(node_id, startup_config)

    from app.xray import refresh_for_subscription

    refresh_for_subscription()

    if structure_changed:
        try:
            fixed = crud.repair_shadowsocks_methods(db)
            if fixed:
                logger.info(
                    "Aligned SS proxy settings for %s users after inbound change",
                    fixed,
                )
        except Exception:
            logger.exception("repair_shadowsocks_methods failed after config save")

    try:
        edge_result = sync_edge_nginx(db)
        if edge_result.warnings:
            logger.warning("edge sync warnings: %s", "; ".join(edge_result.warnings))
        if not edge_result.nginx_applied and edge_result.routes:
            logger.info("edge nginx pending: %s", edge_result.nginx_message)
    except Exception as exc:
        logger.exception("edge sync failed (config saved): %s", exc)

    if applied_without_restart:
        payload = dict(payload)
        payload["_applied_without_restart"] = True
    return payload


@router.get("/core/config/history", responses={403: responses._403})
def list_core_config_history(_: Admin = Depends(require_permission("core:read"))) -> dict:
    """List saved Xray config snapshots (newest first) for rollback."""
    from app.xray import config_history

    return {"snapshots": config_history.list_snapshots()}


@router.post("/core/config/history/{name}/restore", responses={403: responses._403, 404: responses._404})
def restore_core_config(
    name: str,
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Restore a previous Xray config snapshot (validated + applied like a save)."""
    from app.xray import config_history

    snapshot = config_history.read_snapshot(name)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return modify_core_config(payload=snapshot, db=db, admin=admin)


@router.get("/core/tls/suggestions", responses={403: responses._403})
def list_tls_suggestions(_: Admin = _core_read) -> dict:
    """List TLS certificate file pairs discovered on the panel host."""
    from app.xray.tls_presets import discover_tls_certificates

    return {"suggestions": discover_tls_certificates()}


@router.post("/core/tls/self-signed", responses={403: responses._403})
def create_self_signed_tls(
    payload: dict = Body(default={}),
    _: Admin = _core_write,
) -> dict:
    """Generate a self-signed TLS certificate for an inbound."""
    from app.xray.tls_presets import generate_self_signed

    domain = str((payload or {}).get("domain") or (payload or {}).get("serverName") or "").strip()
    if not domain:
        from config import PANEL_PUBLIC_ADDRESS

        host = (PANEL_PUBLIC_ADDRESS or "").replace("https://", "").replace("http://", "").split("/")[0]
        domain = host.split(":")[0] if host else "localhost"
    try:
        return generate_self_signed(domain)
    except subprocess.CalledProcessError as err:
        raise HTTPException(status_code=502, detail=f"openssl failed: {err.stderr or err}") from err
    except (ValueError, RuntimeError) as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@router.post("/core/tls/ech", responses={403: responses._403})
def create_ech_tls(
    payload: dict = Body(default={}),
    _: Admin = _core_write,
) -> dict:
    """Generate ECH server keys and config list for a TLS inbound."""
    from app.xray.tls_presets import generate_ech

    server_name = str(
        (payload or {}).get("serverName")
        or (payload or {}).get("domain")
        or (payload or {}).get("sni")
        or ""
    ).strip()
    if not server_name:
        from config import PANEL_PUBLIC_ADDRESS

        host = (PANEL_PUBLIC_ADDRESS or "").replace("https://", "").replace("http://", "").split("/")[0]
        server_name = host.split(":")[0] if host else ""
    try:
        return generate_ech(server_name)
    except (ValueError, RuntimeError) as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except subprocess.CalledProcessError as err:
        raise HTTPException(
            status_code=502,
            detail=f"xray tls ech failed: {(err.stderr or err.stdout or err)}",
        ) from err


@router.get("/core/wireguard/keypair", responses={403: responses._403})
def generate_wireguard_keypair(_: Admin = _core_read) -> dict:
    """Generate a WireGuard X25519 keypair for inbound/outbound editors."""
    from app.wireguard import generate_keypair

    private_key, public_key = generate_keypair()
    return {"privateKey": private_key, "publicKey": public_key}


@router.post("/core/reality/keypair", responses={403: responses._403})
@router.post("/xray/generate-keys", responses={403: responses._403})
def generate_reality_keypair(_: Admin = _core_read) -> dict:
    """Generate a VLESS Reality x25519 keypair via ``xray x25519``."""
    from app.tunnel import generate_reality_keys

    try:
        keys = generate_reality_keys()
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    return {"privateKey": keys["private_key"], "publicKey": keys["public_key"]}


@router.get("/core/vlessenc", responses={403: responses._403})
def generate_vlessenc(
    type: str = "x25519",
    _: Admin = _core_write,
) -> dict:
    """Generate VLESS decryption/encryption pair via ``xray vlessenc``."""
    from app.xray.vlessenc import run_vlessenc

    try:
        return run_vlessenc(type)
    except (RuntimeError, ValueError) as err:
        raise HTTPException(status_code=502, detail=str(err)) from err


@router.get("/core/warp", responses={403: responses._403})
def get_warp_account(admin: Admin = _core_write) -> dict:
    """Return registered Cloudflare WARP account(s)."""
    store = warp.list_warp_accounts()
    if not store.get("accounts"):
        return {"registered": False, "accounts": {}}
    return {"registered": True, **store}


@router.get("/core/warp/{tag}", responses={403: responses._403})
def get_warp_account_by_tag(tag: str, admin: Admin = _core_write) -> dict:
    data = warp.get_warp(tag=tag)
    if not data:
        raise HTTPException(status_code=404, detail="WARP account not found")
    return data


@router.post("/core/warp/register", responses={403: responses._403})
def register_warp_account(
    payload: dict = Body(default={}),
    admin: Admin = _core_write,
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
    admin: Admin = _core_write,
) -> dict:
    """Apply a WARP+ license key to the registered device."""
    license_key = (payload or {}).get("license", "").strip()
    if not license_key:
        raise HTTPException(status_code=400, detail="license is required")
    tag = (payload or {}).get("tag")
    try:
        return warp.set_warp_license(license_key, tag=tag)
    except warp.WarpError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err


@router.delete("/core/warp", responses={403: responses._403})
def delete_warp_account(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Forget all WARP credentials and reset master routing to DIRECT."""
    from app.services.warp_core import clear_node_warp_refs
    from app.xray.warp_routing import strip_warp_from_config

    store = warp.list_warp_accounts()
    tags = list((store.get("accounts") or {}).keys())
    warp.delete_warp_data()
    affected = clear_node_warp_refs(db, tags=None)
    cfg = strip_warp_from_config(_current_config_dict())
    modify_core_config(payload=cfg, db=db, admin=admin)
    for node_id in affected:
        bg.add_task(xray.operations.restart_node, node_id)
    return {"registered": False, "routing_reset": True, "cleared_tags": tags}


@router.delete("/core/warp/{tag}", responses={403: responses._403})
def delete_warp_account_tag(
    tag: str,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Forget one WARP account and remove its outbound/routing from master config."""
    from app.services.warp_core import clear_node_warp_refs
    from app.xray.warp_routing import strip_warp_from_config

    warp.delete_warp_data(tag=tag)
    affected = clear_node_warp_refs(db, tags=[tag])
    cfg = strip_warp_from_config(_current_config_dict(), tags=[tag])
    modify_core_config(payload=cfg, db=db, admin=admin)
    for node_id in affected:
        bg.add_task(xray.operations.restart_node, node_id)
    return {"deleted": tag, "routing_reset": True}


def _current_config_dict() -> dict:
    with open(XRAY_JSON, "r") as f:
        return commentjson.loads(f.read())


def _tag_of(entry: dict) -> str:
    return str((entry or {}).get("tag") or "")


# ------------------------------------------------------------------ outbounds

@router.get("/core/outbounds", responses={403: responses._403})
def list_core_outbounds(_: Admin = _core_read) -> dict:
    """List outbounds from the current core config (granular CRUD helper)."""
    return {"outbounds": _current_config_dict().get("outbounds") or []}


@router.put("/core/outbounds", responses={403: responses._403})
def reorder_core_outbounds(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Replace the whole outbounds array (used for reorder / bulk edit)."""
    outbounds = payload.get("outbounds")
    if not isinstance(outbounds, list):
        raise HTTPException(status_code=400, detail="'outbounds' array is required")
    for outbound in outbounds:
        if not isinstance(outbound, dict) or not _tag_of(outbound):
            raise HTTPException(status_code=400, detail="each outbound must have a 'tag'")
    cfg = _current_config_dict()
    cfg["outbounds"] = outbounds
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.post("/core/outbounds", responses={403: responses._403, 409: responses._409})
def add_core_outbound(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Add a single outbound by tag (validated + applied like a full save)."""
    outbound = payload.get("outbound") if "outbound" in payload else payload
    if not isinstance(outbound, dict) or not _tag_of(outbound):
        raise HTTPException(status_code=400, detail="outbound with a 'tag' is required")
    cfg = _current_config_dict()
    outbounds = list(cfg.get("outbounds") or [])
    if any(_tag_of(o) == _tag_of(outbound) for o in outbounds):
        raise HTTPException(status_code=409, detail=f"Outbound tag '{_tag_of(outbound)}' already exists")
    outbounds.append(outbound)
    cfg["outbounds"] = outbounds
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.put("/core/outbounds/{tag}", responses={403: responses._403, 404: responses._404})
def update_core_outbound(
    tag: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Replace the outbound with ``tag``."""
    outbound = payload.get("outbound") if "outbound" in payload else payload
    if not isinstance(outbound, dict):
        raise HTTPException(status_code=400, detail="outbound object is required")
    cfg = _current_config_dict()
    outbounds = list(cfg.get("outbounds") or [])
    idx = next((i for i, o in enumerate(outbounds) if _tag_of(o) == tag), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Outbound '{tag}' not found")
    outbound.setdefault("tag", tag)
    outbounds[idx] = outbound
    cfg["outbounds"] = outbounds
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.delete("/core/outbounds/{tag}", responses={403: responses._403, 404: responses._404})
def delete_core_outbound(
    tag: str,
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Remove the outbound with ``tag`` (WARP tags also reset routing to DIRECT)."""
    from app.xray.warp_routing import is_warp_tag, strip_warp_from_config

    cfg = _current_config_dict()
    outbounds = list(cfg.get("outbounds") or [])
    kept = [o for o in outbounds if _tag_of(o) != tag]
    if len(kept) == len(outbounds):
        raise HTTPException(status_code=404, detail=f"Outbound '{tag}' not found")
    if is_warp_tag(tag):
        cfg = strip_warp_from_config(cfg, tags=[tag])
    else:
        cfg["outbounds"] = kept
    return modify_core_config(payload=cfg, db=db, admin=admin)


# --------------------------------------------------------------- routing rules

def _routing(cfg: dict) -> dict:
    routing = cfg.get("routing")
    if not isinstance(routing, dict):
        routing = {}
        cfg["routing"] = routing
    return routing


@router.patch("/core/routing", responses={403: responses._403})
def patch_routing_meta(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Update routing metadata (e.g. ``domainStrategy``) without bulk config PUT."""
    cfg = _current_config_dict()
    routing = _routing(cfg)
    if "domainStrategy" in payload:
        routing["domainStrategy"] = payload["domainStrategy"]
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.get("/core/routing/rules", responses={403: responses._403})
def list_routing_rules(_: Admin = _core_read) -> dict:
    """List routing rules (with their index) from the current config."""
    routing = _routing(_current_config_dict())
    return {
        "rules": list(routing.get("rules") or []),
        "domainStrategy": routing.get("domainStrategy"),
    }


@router.post("/core/routing/rules", responses={403: responses._403})
def add_routing_rule(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Insert a routing rule. Optional ``index`` positions it (default: before catch-all)."""
    from app.xray.warp_routing import insert_rule_before_catchall

    rule = payload.get("rule") if "rule" in payload else payload
    if not isinstance(rule, dict):
        raise HTTPException(status_code=400, detail="rule object is required")
    index = payload.get("index") if isinstance(payload, dict) else None
    cfg = _current_config_dict()
    routing = _routing(cfg)
    rules = list(routing.get("rules") or [])
    if isinstance(index, int) and 0 <= index <= len(rules):
        rules.insert(index, rule)
    else:
        rules = insert_rule_before_catchall(rules, rule)
    routing["rules"] = rules
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.put("/core/routing/rules", responses={403: responses._403})
def reorder_routing_rules(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Replace the whole rules array (used for reorder / bulk edit)."""
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise HTTPException(status_code=400, detail="'rules' array is required")
    cfg = _current_config_dict()
    _routing(cfg)["rules"] = rules
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.put("/core/routing/rules/{index}", responses={403: responses._403, 404: responses._404})
def update_routing_rule(
    index: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Replace the routing rule at ``index``."""
    rule = payload.get("rule") if "rule" in payload else payload
    if not isinstance(rule, dict):
        raise HTTPException(status_code=400, detail="rule object is required")
    cfg = _current_config_dict()
    routing = _routing(cfg)
    rules = list(routing.get("rules") or [])
    if not 0 <= index < len(rules):
        raise HTTPException(status_code=404, detail="Rule index out of range")
    rules[index] = rule
    routing["rules"] = rules
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.delete("/core/routing/rules/{index}", responses={403: responses._403, 404: responses._404})
def delete_routing_rule(
    index: int,
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Remove the routing rule at ``index``."""
    cfg = _current_config_dict()
    routing = _routing(cfg)
    rules = list(routing.get("rules") or [])
    if not 0 <= index < len(rules):
        raise HTTPException(status_code=404, detail="Rule index out of range")
    rules.pop(index)
    routing["rules"] = rules
    return modify_core_config(payload=cfg, db=db, admin=admin)


# ----------------------------------------------------------------- balancers

@router.get("/core/routing/balancers", responses={403: responses._403})
def list_balancers(_: Admin = _core_read) -> dict:
    """List routing balancers from the current config."""
    return {"balancers": list(_routing(_current_config_dict()).get("balancers") or [])}


@router.post("/core/routing/balancers", responses={403: responses._403, 409: responses._409})
def add_balancer(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Add a balancer by ``tag`` (selector list + optional strategy)."""
    balancer = payload.get("balancer") if "balancer" in payload else payload
    if not isinstance(balancer, dict) or not _tag_of(balancer):
        raise HTTPException(status_code=400, detail="balancer with a 'tag' is required")
    cfg = _current_config_dict()
    routing = _routing(cfg)
    balancers = list(routing.get("balancers") or [])
    if any(_tag_of(b) == _tag_of(balancer) for b in balancers):
        raise HTTPException(status_code=409, detail=f"Balancer '{_tag_of(balancer)}' already exists")
    balancers.append(balancer)
    routing["balancers"] = balancers
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.put("/core/routing/balancers/{tag}", responses={403: responses._403, 404: responses._404})
def update_balancer(
    tag: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Replace the balancer with ``tag``."""
    balancer = payload.get("balancer") if "balancer" in payload else payload
    if not isinstance(balancer, dict):
        raise HTTPException(status_code=400, detail="balancer object is required")
    cfg = _current_config_dict()
    routing = _routing(cfg)
    balancers = list(routing.get("balancers") or [])
    idx = next((i for i, b in enumerate(balancers) if _tag_of(b) == tag), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Balancer '{tag}' not found")
    balancer.setdefault("tag", tag)
    balancers[idx] = balancer
    routing["balancers"] = balancers
    return modify_core_config(payload=cfg, db=db, admin=admin)


@router.delete("/core/routing/balancers/{tag}", responses={403: responses._403, 404: responses._404})
def delete_balancer(
    tag: str,
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Remove the balancer with ``tag``."""
    cfg = _current_config_dict()
    routing = _routing(cfg)
    balancers = list(routing.get("balancers") or [])
    kept = [b for b in balancers if _tag_of(b) != tag]
    if len(kept) == len(balancers):
        raise HTTPException(status_code=404, detail=f"Balancer '{tag}' not found")
    routing["balancers"] = kept
    return modify_core_config(payload=cfg, db=db, admin=admin)


# ---------------------------------------------------------- geo assets (.dat)

import hashlib
import os
import re

_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.dat$")
# Well-known community geo data (Loyalsoldier) — overridable per request.
_DEFAULT_ASSET_SOURCES = {
    "geoip.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat",
    "geosite.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat",
}


def _safe_asset_path(name: str) -> str:
    """Resolve ``name`` inside the assets dir, rejecting traversal/bad names."""
    if not _ASSET_NAME_RE.match(name or ""):
        raise HTTPException(status_code=400, detail="Invalid asset name (expected *.dat)")
    base = os.path.realpath(XRAY_ASSETS_PATH)
    full = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(full) != base:
        raise HTTPException(status_code=400, detail="Invalid asset path")
    return full


@router.get("/core/assets", responses={403: responses._403})
def list_geo_assets(_: Admin = _core_read) -> dict:
    """List geoip/geosite ``.dat`` files with size, mtime and sha256."""
    base = XRAY_ASSETS_PATH
    out = []
    try:
        names = sorted(n for n in os.listdir(base) if n.endswith(".dat"))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(base, name)
        try:
            st = os.stat(path)
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            out.append({
                "name": name,
                "size": st.st_size,
                "modified_at": int(st.st_mtime),
                "sha256": digest,
            })
        except OSError:
            continue
    return {"path": base, "assets": out}


@router.post("/core/assets/upload", responses={403: responses._403})
def upload_geo_asset(
    file: UploadFile = File(...),
    _: Admin = _core_write,
) -> dict:
    """Upload/replace a ``.dat`` asset file."""
    dest = _safe_asset_path(file.filename or "")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return {"name": os.path.basename(dest), "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


@router.post("/core/assets/update", responses={403: responses._403, 502: responses._400})
def update_geo_assets(
    payload: dict = Body(default={}),
    _: Admin = _core_write,
) -> dict:
    """Download the latest geoip.dat/geosite.dat from a source URL map.

    ``payload.sources`` maps ``name -> url``; defaults to the Loyalsoldier
    community release. Files are written atomically only after a full download.
    """
    import requests

    sources = (payload or {}).get("sources") or _DEFAULT_ASSET_SOURCES
    os.makedirs(XRAY_ASSETS_PATH, exist_ok=True)
    results = []
    for name, url in sources.items():
        dest = _safe_asset_path(name)
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.content
            if not data:
                raise ValueError("empty download")
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            results.append({"name": name, "ok": True, "size": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
        except Exception as exc:  # network / write errors
            logger.warning("Geo asset update failed for %s: %s", name, exc)
            results.append({"name": name, "ok": False, "error": str(exc)})
    return {"path": XRAY_ASSETS_PATH, "results": results}


@router.delete("/core/assets/{name}", responses={403: responses._403, 404: responses._404})
def delete_geo_asset(
    name: str,
    _: Admin = _core_write,
) -> dict:
    """Delete a ``.dat`` asset file."""
    path = _safe_asset_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Asset not found")
    os.remove(path)
    return {"deleted": name}


@router.post("/core/outbounds/test", responses={403: responses._403})
def test_core_outbound(
    payload: dict = Body(...),
    admin: Admin = _core_read,
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
    node_id = payload.get("node_id")
    if node_id is not None:
        from app import xray
        from app.xray.node import NodeAPIError

        node = xray.nodes.get(int(node_id))
        if not node or not getattr(node, "connected", False):
            raise HTTPException(status_code=404, detail="Node not connected")
        try:
            return node.make_request("/outbound/test", timeout=30, outbound=outbound)
        except NodeAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = test_outbound(outbound, all_outbounds, test_url=test_url, mode=mode)
    return result.to_dict()


def _read_core_config_file() -> dict:
    with open(XRAY_JSON, "r", encoding="utf-8") as f:
        return commentjson.loads(f.read())


def _parse_inbound_import_payload(payload: dict) -> dict:
    """Accept ``{inbound: {...}}`` or a bare inbound object."""
    inbound = payload.get("inbound") if isinstance(payload.get("inbound"), dict) else payload
    if not isinstance(inbound, dict) or not inbound.get("tag"):
        raise HTTPException(status_code=400, detail="inbound object with tag is required")
    return dict(inbound)


def _merge_inbound_into_config(config: dict, inbound: dict) -> dict:
    inbounds = list(config.get("inbounds") or [])
    tag = str(inbound["tag"])
    replaced = False
    for i, existing in enumerate(inbounds):
        if existing.get("tag") == tag:
            inbounds[i] = inbound
            replaced = True
            break
    if not replaced:
        inbounds.append(inbound)
    merged = dict(config)
    merged["inbounds"] = inbounds
    return merged


@router.get("/core/inbounds/{tag}/export", responses={403: responses._403, 404: responses._404})
def export_inbound(
    tag: str,
    admin: Admin = _core_read,
) -> dict:
    """Export a single inbound JSON object by tag."""
    config = _read_core_config_file()
    for inbound in config.get("inbounds") or []:
        if inbound.get("tag") == tag:
            return {"inbound": inbound}
    raise HTTPException(status_code=404, detail=f"Inbound {tag} not found")


@router.post("/core/inbounds/{tag}/import", responses={403: responses._403, 400: responses._400})
def import_inbound_by_tag(
    tag: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Import/replace one inbound; ``tag`` in the path always wins over body."""
    inbound = _parse_inbound_import_payload(payload)
    inbound["tag"] = tag
    config = _merge_inbound_into_config(_read_core_config_file(), inbound)
    return modify_core_config(payload=config, db=db, admin=admin)


@router.post("/core/inbounds/import", responses={403: responses._403, 400: responses._400})
def import_inbound(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Import one inbound into the core config (replace same tag or append)."""
    inbound = _parse_inbound_import_payload(payload)
    config = _merge_inbound_into_config(_read_core_config_file(), inbound)
    return modify_core_config(payload=config, db=db, admin=admin)


class AcmeIssueBody(BaseModel):
    domain: str
    email: str = "admin@localhost"


@router.post("/core/acme/issue", responses={403: responses._403})
def issue_core_acme_cert(
    body: AcmeIssueBody,
    _: Admin = _core_write,
) -> dict:
    from app.tls.acme import issue_certificate, normalize_tls_target

    target = normalize_tls_target(body.domain)
    cert_pem, _key_pem = issue_certificate(target, body.email)
    return {"domain": body.domain, "cert": cert_pem[:80] + "…", "issued": True}


@router.get("/core/inbounds/presets", responses={403: responses._403})
def list_inbound_presets(_: Admin = _core_read) -> dict:
    from app.xray.inbound_presets import INBOUND_PRESETS

    return {"presets": INBOUND_PRESETS}


@router.get("/core/inbounds/singbox", responses={403: responses._403})
def list_singbox_inbounds(
    db: Session = Depends(get_db),
    _: Admin = _core_read,
) -> dict:
    """Virtual TUIC/AnyTLS inbounds enabled on nodes (sing-box engine)."""
    from app.singbox.inbound_registry import list_singbox_inbound_entries

    return {"inbounds": list_singbox_inbound_entries(db)}


class SingboxInboundApplyBody(BaseModel):
    node_id: int
    port: int | None = None
    tuic_congestion_control: str | None = None


@router.post("/core/inbounds/presets/{preset_id}/apply", responses={403: responses._403, 404: responses._404})
def apply_inbound_preset(
    preset_id: str,
    body: SingboxInboundApplyBody,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Apply an inbound preset. sing-box presets enable TUIC/AnyTLS on a node."""
    from app.xray.inbound_presets import INBOUND_PRESETS

    preset = INBOUND_PRESETS.get(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Unknown inbound preset '{preset_id}'")

    if preset.get("deploy") == "singbox":
        from app.singbox.inbound_registry import apply_singbox_inbound_preset
        from app.routers.node import _sync_singbox_node

        result = apply_singbox_inbound_preset(
            db,
            preset_id,
            node_id=body.node_id,
            port=body.port,
            tuic_congestion_control=body.tuic_congestion_control,
        )
        bg.add_task(_sync_singbox_node, body.node_id)
        result["sync"] = "scheduled"
        return result

    inbound = preset.get("inbound")
    if not isinstance(inbound, dict):
        raise HTTPException(status_code=400, detail=f"Preset '{preset_id}' has no Xray inbound template")

    cfg = _current_config_dict()
    tag = _tag_of(inbound)
    inbounds = list(cfg.get("inbounds") or [])
    if any(_tag_of(i) == tag for i in inbounds):
        raise HTTPException(status_code=409, detail=f"Inbound tag '{tag}' already exists")
    inbounds.append(inbound)
    cfg["inbounds"] = inbounds
    saved = modify_core_config(payload=cfg, db=db, admin=admin)
    return {"preset_id": preset_id, "inbound": inbound, "config": saved}


@router.post(
    "/core/inbounds/singbox/{node_id}/{protocol}/disable",
    responses={403: responses._403, 404: responses._404},
)
def disable_singbox_inbound_route(
    node_id: int,
    protocol: str,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    _: Admin = _core_write,
) -> dict:
    from app.singbox.inbound_registry import disable_singbox_inbound
    from app.routers.node import _sync_singbox_node

    if protocol not in ("tuic", "anytls"):
        raise HTTPException(status_code=400, detail="protocol must be tuic or anytls")
    result = disable_singbox_inbound(db, node_id, protocol)  # type: ignore[arg-type]
    bg.add_task(_sync_singbox_node, node_id)
    result["sync"] = "scheduled"
    return result


@router.get("/core/observatory", responses={403: responses._403})
def get_observatory_config(_: Admin = _core_read) -> dict:
    with open(XRAY_JSON, "r") as f:
        config = commentjson.loads(f.read())
    return {
        "observatory": config.get("observatory"),
        "burstObservatory": config.get("burstObservatory"),
    }


@router.put("/core/observatory", responses={403: responses._403})
def set_observatory_config(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    with open(XRAY_JSON, "r") as f:
        config = commentjson.loads(f.read())
    if "observatory" in payload:
        config["observatory"] = payload.get("observatory")
    if "burstObservatory" in payload:
        config["burstObservatory"] = payload.get("burstObservatory")
    return modify_core_config(payload=config, db=db, admin=admin)


@router.get("/core/outbound-presets", responses={403: responses._403})
def list_outbound_presets(_: Admin = _core_read) -> dict:
    from app.outbound.presets import OUTBOUND_PRESETS

    return {"presets": OUTBOUND_PRESETS}


@router.post("/core/outbound-presets/{preset_id}/apply", responses={403: responses._403, 404: responses._404})
def apply_outbound_preset(
    preset_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = _core_write,
) -> dict:
    """Merge an outbound pool preset (upstreams + balancer + observatory) into core config."""
    from app.outbound.apply import build_pool_bundle, get_preset, merge_pool_bundle

    get_preset(preset_id)
    upstreams = payload.get("upstreams") or []
    if not isinstance(upstreams, list):
        raise HTTPException(status_code=400, detail="upstreams must be a list")

    bundle = build_pool_bundle(
        preset_id,
        upstreams=upstreams,
        balancer_tag=payload.get("balancer_tag"),
        strategy=str(payload.get("strategy") or get_preset(preset_id).get("default_strategy") or "leastPing"),
        tag_prefix=payload.get("tag_prefix"),
        enable_observatory=bool(payload.get("enable_observatory", True)),
        probe_url=str(payload.get("probe_url") or "https://www.google.com/generate_204"),
        probe_interval=str(payload.get("probe_interval") or "10s"),
    )

    cfg = _current_config_dict()
    merged = merge_pool_bundle(
        cfg,
        bundle,
        replace_existing=bool(payload.get("replace_existing", True)),
        add_routing_rule=bool(payload.get("add_routing_rule", False)),
    )
    result = modify_core_config(payload=merged, db=db, admin=admin)
    return {
        "config": result,
        "applied": {
            "preset_id": preset_id,
            "outbound_tags": [o.get("tag") for o in bundle.get("outbounds") or []],
            "balancer_tag": (bundle.get("balancers") or [{}])[0].get("tag"),
            "observatory": bool(bundle.get("observatory")),
        },
    }
