import os
from typing import List

from fastapi import APIRouter, Depends
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
