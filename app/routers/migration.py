"""3x-ui migration API."""
from __future__ import annotations

import threading
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import logger
from app.db import GetDB, Session, get_db
from app.migration import jobs as migration_jobs
from app.migration.sqlite_dump import save_uploaded_backup
from app.migration.three_x_ui import MigrationFetchError, MigrationResult, PanelSource, run_batch
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["Migration"],
    prefix="/api/migration",
    responses={401: responses._401, 403: responses._403},
)


class ThreeXUIPanelIn(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    base_url: str = ""
    username: str = ""
    password: str = ""
    backup_path: str = ""
    legacy_panel_id: str = ""


class ThreeXUIMigrateRequest(BaseModel):
    panels: List[ThreeXUIPanelIn]
    dry_run: bool = True


@router.post("/3x-ui/upload")
async def upload_backup_file(
    file: UploadFile = File(...),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Upload a 3x-ui .dump / .db backup; returns server path for migration wizard."""
    name = (file.filename or "backup.dump").strip()
    lower = name.lower()
    if not lower.endswith((".dump", ".sql", ".db", ".sqlite", ".sqlite3", ".json")):
        raise HTTPException(
            status_code=400,
            detail="Supported backup types: .dump, .sql, .db, .sqlite, .json",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty backup file")
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Backup file too large (max 100MB)")
    try:
        path = save_uploaded_backup(content, name)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot save backup: {exc}") from exc
    return {"path": path, "filename": name}


@router.post("/3x-ui/dry-run")
def migration_dry_run(
    body: ThreeXUIMigrateRequest,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    return _run_migration(body, db)


def _post_migration_sync(db: Session, *, applied: bool) -> None:
    try:
        from app import app
        from app.routers import api_router
        from app.subscription.route_registry import refresh_subscription_routes

        refresh_subscription_routes(app, api_router)
    except Exception:
        logger.exception("Post-migration subscription route refresh failed")

    # Issue/activate LE + :443 vhosts for every subscription host, then HUP
    # host nginx with --pid host so new SNI certs are live (without this,
    # srwN kept serving the default panel cert until a manual reload).
    try:
        from app.db import crud
        from app.services.edge_proxy import (
            finalize_subscription_ssl_after_migration,
            force_reload_subscription_nginx,
        )

        hosts: list[str] = []
        seen: set[str] = set()
        for ep in crud.list_subscription_endpoints(db, enabled_only=True):
            host = (ep.host or "").strip().lower().split(":")[0]
            if not host or host == "_" or host in seen:
                continue
            seen.add(host)
            hosts.append(host)

        if hosts:
            for host in hosts:
                result = finalize_subscription_ssl_after_migration(db, host)
                logger.info(
                    "post-migration SSL host=%s https_ready=%s nginx_reloaded=%s",
                    host,
                    result.get("https_ready"),
                    result.get("nginx_reloaded"),
                )
        else:
            ok, msg = force_reload_subscription_nginx()
            logger.info("post-migration nginx reload ok=%s msg=%s", ok, (msg or "")[:200])
    except Exception:
        logger.exception("Post-migration subscription SSL/nginx finalize failed")

    if applied:
        try:
            from app.xray.serving import sync_core_users_now

            sync_core_users_now()
        except Exception:
            logger.exception("Post-migration core user sync failed")


def _run_migration_job(job_id: str, sources: List[PanelSource]) -> None:
    """Background worker: full import + post-sync, streaming progress to the job."""
    def progress(processed_delta: int = 0, total_delta: int = 0) -> None:
        migration_jobs.bump_progress(job_id, processed_delta, total_delta)

    try:
        with GetDB() as db:
            batch = run_batch(db, sources, dry_run=False, progress_cb=progress)
            results = [_result_dict(r) for r in batch.results]
            applied = any(r.applied for r in batch.results)
            _post_migration_sync(db, applied=applied)
        migration_jobs.finish(
            job_id,
            state="done",
            results=results,
            uuid_collisions=batch.uuid_collisions,
        )
    except MigrationFetchError as exc:
        migration_jobs.finish(job_id, state="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface any failure to the poller
        logger.exception("Background migration job %s failed", job_id)
        migration_jobs.finish(job_id, state="error", error=f"Migration failed: {exc}")


@router.post("/3x-ui/run")
def migration_run(
    body: ThreeXUIMigrateRequest,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    # Dry-run (preview) is cheap and read-only — keep it synchronous.
    if body.dry_run:
        result = _run_migration(body, db)
        _post_migration_sync(db, applied=False)
        return result

    # A real import can process thousands of clients (tens of seconds), which
    # outlives reverse-proxy/client timeouts. Run it in the background and let
    # the client poll /3x-ui/status/{job_id} instead of holding the request.
    sources = _validated_sources(body)

    active = migration_jobs.active_job()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="A migration is already running. Wait for it to finish.",
        )

    job = migration_jobs.create()
    thread = threading.Thread(
        target=_run_migration_job,
        args=(job.id, sources),
        name=f"migration-{job.id[:8]}",
        daemon=True,
    )
    thread.start()
    return {"job_id": job.id, "state": job.state, "async": True}


@router.get("/3x-ui/status/{job_id}")
def migration_status(
    job_id: str,
    _: Admin = Depends(Admin.check_sudo_admin),
):
    job = migration_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired migration job")
    return job.to_dict()


def _result_dict(r: MigrationResult) -> dict:
    return {
        "panel_slug": r.panel_slug,
        "applied": r.applied,
        "endpoint": r.endpoint,
        "inbound_tags": r.inbound_tags,
        "user_count": r.user_count,
        "alias_count": r.alias_count,
        "users_created": r.users_created,
        "users_updated": r.users_updated,
        "aliases_created": r.aliases_created,
        "hosts_created": r.hosts_created,
        "validation": r.validation,
        "warnings": r.warnings,
        "error": r.error,
    }


def _validated_sources(body: ThreeXUIMigrateRequest) -> List[PanelSource]:
    sources = [PanelSource(**p.model_dump()) for p in body.panels]
    if not sources:
        raise HTTPException(status_code=400, detail="Add at least one panel")
    for src in sources:
        slug = (src.slug or "").strip()
        if not slug:
            raise HTTPException(status_code=400, detail="Each panel needs a slug")
        has_api = bool((src.base_url or "").strip())
        has_backup = bool((src.backup_path or "").strip())
        if has_api and has_backup:
            raise HTTPException(
                status_code=400,
                detail=f"Panel «{slug}»: use either live API or backup file, not both",
            )
        if not has_api and not has_backup:
            raise HTTPException(
                status_code=400,
                detail=f"Panel «{slug}»: provide panel URL (API) or backup file path",
            )
        if has_api and (not (src.username or "").strip() or not (src.password or "").strip()):
            raise HTTPException(
                status_code=400,
                detail=f"Panel «{slug}»: admin username and password required for API import",
            )
    return sources


def _run_migration(body: ThreeXUIMigrateRequest, db: Session) -> dict:
    sources = _validated_sources(body)
    try:
        batch = run_batch(db, sources, dry_run=body.dry_run)
    except MigrationFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Migration failed: {exc}") from exc
    payload: dict = {"results": [_result_dict(r) for r in batch.results]}
    if batch.uuid_collisions:
        payload["uuid_collisions"] = batch.uuid_collisions
    return payload
