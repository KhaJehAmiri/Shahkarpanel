from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import feature_flags, plugins
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["Plugins"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)


class PluginInfo(BaseModel):
    name: str
    description: str


class PluginsStatus(BaseModel):
    enabled: bool
    plugins: List[PluginInfo]


@router.get("/plugins", response_model=PluginsStatus)
def list_plugins(_: Admin = Depends(Admin.check_sudo_admin)):
    """List loaded plugins and whether the plugin system is enabled."""
    return PluginsStatus(
        enabled=feature_flags.is_enabled("plugins"),
        plugins=[
            PluginInfo(name=p.name, description=p.description)
            for p in plugins.get_plugins()
        ],
    )
