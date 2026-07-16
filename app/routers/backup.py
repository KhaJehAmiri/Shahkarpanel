import os
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import backup as backup_module
from app.models.admin import Admin
from app.rbac import require_permission
from app.utils import responses

MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def _resolve_backup(filename: str) -> str:
    if not filename or "/" in filename or ".." in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    match = next(
        (p for p in backup_module.list_backups() if os.path.basename(p) == filename),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    return match


router = APIRouter(
    tags=["Backup"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)

_backup_read = Depends(require_permission("backup:read"))
_backup_write = Depends(require_permission("backup:write"))


class BackupResponse(BaseModel):
    path: str
    filename: str = ""


@router.get("/backup/download")
def download_backup_now(_: Admin = _backup_read):
    """Create a fresh DB backup and download it immediately (3x-ui style)."""
    try:
        path, name = backup_module.create_downloadable_backup()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    media = "application/octet-stream"
    lower = name.lower()
    if lower.endswith(".dump"):
        media = "application/vnd.postgresql.dump"
    elif lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        media = "application/gzip"
    return FileResponse(path, media_type=media, filename=name)


@router.post("/backup/restore")
async def restore_backup_upload(
    file: UploadFile = File(...),
    _: Admin = _backup_write,
):
    """Upload a backup and restore it in one step (3x-ui style). Panel restarts after."""
    name = (file.filename or "backup").strip()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty backup file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Backup file too large")
    try:
        stored = backup_module.restore_from_bytes(content, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Restore failed: {exc}") from exc
    return {
        "detail": "Backup restored",
        "filename": stored,
        "restarting": True,
    }


@router.post("/backup", response_model=BackupResponse)
def create_backup(_: Admin = _backup_write):
    """Create a backup archive on the server (kept under BACKUP_DIR)."""
    try:
        path = backup_module.create_backup()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return BackupResponse(path=path, filename=os.path.basename(path))


@router.get("/backups", response_model=List[str])
def list_backups(_: Admin = _backup_read):
    """List available backup archives on the server."""
    return [os.path.basename(p) for p in backup_module.list_backups()]


@router.get("/backups/schedule")
def backup_schedule(_: Admin = _backup_read):
    from app.utils.runtime_settings import backup_interval_hours

    hours = backup_interval_hours()
    return {
        "enabled": hours > 0,
        "interval_hours": hours,
    }


class BackupScheduleBody(BaseModel):
    interval_hours: int = 0


@router.put("/backups/schedule")
def update_backup_schedule(
    body: BackupScheduleBody,
    _: Admin = _backup_write,
):
    from app.jobs.backup import reschedule_backup_job
    from app.utils.runtime_settings import set_value

    hours = max(0, min(int(body.interval_hours), 168))
    set_value("backup_interval_hours", hours)
    reschedule_backup_job()
    return {"enabled": hours > 0, "interval_hours": hours}


@router.post("/backups/upload")
async def upload_backup_archive(
    file: UploadFile = File(...),
    _: Admin = _backup_write,
):
    """Upload a backup file to the server without restoring it yet."""
    name = (file.filename or "backup").strip()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty backup file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Backup file too large")
    try:
        stored = backup_module.save_uploaded_backup(content, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot save backup: {exc}") from exc
    return {"filename": stored}


@router.get("/backups/{filename}/download")
def download_backup_archive(
    filename: str,
    _: Admin = _backup_read,
):
    """Download a previously stored backup from the server."""
    match = _resolve_backup(filename)
    return FileResponse(
        match,
        media_type="application/octet-stream",
        filename=os.path.basename(match),
    )


@router.post("/backups/{filename}/restore")
def restore_backup_archive(
    filename: str,
    _: Admin = _backup_write,
):
    """Restore a named backup already stored on the server."""
    match = _resolve_backup(filename)
    try:
        backup_module.restore_backup(match)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"detail": "Backup restored", "restarting": True}


@router.delete("/backups/{filename}")
def delete_backup_archive(
    filename: str,
    _: Admin = _backup_write,
):
    """Delete a stored backup file."""
    try:
        backup_module.delete_backup(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup not found")
    return {"detail": "Backup deleted"}
