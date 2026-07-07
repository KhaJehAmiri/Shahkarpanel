import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import backup as backup_module
from app.models.admin import Admin
from app.rbac import require_permission
from app.utils import responses

router = APIRouter(
    tags=["Backup"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)

_backup_read = Depends(require_permission("backup:read"))
_backup_write = Depends(require_permission("backup:write"))


class BackupResponse(BaseModel):
    path: str


@router.post("/backup", response_model=BackupResponse)
def create_backup(_: Admin = _backup_write):
    """Create a backup archive now."""
    path = backup_module.create_backup()
    return BackupResponse(path=path)


@router.get("/backups", response_model=List[str])
def list_backups(_: Admin = _backup_read):
    """List available backup archives."""
    return [os.path.basename(p) for p in backup_module.list_backups()]


@router.post("/backups/{filename}/restore")
def restore_backup_archive(
    filename: str,
    _: Admin = _backup_write,
):
    """Restore a named backup archive (SQLite: automatic; PG: extracts SQL dump)."""
    if not filename or "/" in filename or ".." in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    backups = backup_module.list_backups()
    match = next((p for p in backups if os.path.basename(p) == filename), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    try:
        backup_module.restore_backup(match)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"detail": "Backup restored"}


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
