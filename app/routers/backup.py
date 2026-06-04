import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import backup as backup_module
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["Backup"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)


class BackupResponse(BaseModel):
    path: str


@router.post("/backup", response_model=BackupResponse)
def create_backup(_: Admin = Depends(Admin.check_sudo_admin)):
    """Create a backup archive now. Accessible only to sudo admins."""
    path = backup_module.create_backup()
    return BackupResponse(path=path)


@router.get("/backups", response_model=List[str])
def list_backups(_: Admin = Depends(Admin.check_sudo_admin)):
    """List available backup archives. Accessible only to sudo admins."""
    return [os.path.basename(p) for p in backup_module.list_backups()]


@router.post("/backups/{filename}/restore")
def restore_backup_archive(
    filename: str,
    _: Admin = Depends(Admin.check_sudo_admin),
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
