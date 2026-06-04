from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import feature_flags, marketplace
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["Marketplace"],
    prefix="/api/marketplace",
    responses={401: responses._401, 403: responses._403},
)


class PluginInfo(BaseModel):
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    source_url: Optional[str] = None
    installed: bool
    enabled: bool
    rating: float
    rating_count: int


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class ReviewResponse(BaseModel):
    rating: int
    comment: Optional[str] = None
    created_at: datetime


def _require_enabled():
    if not feature_flags.is_enabled("plugin_marketplace"):
        raise HTTPException(status_code=404, detail="Plugin marketplace is disabled")


def _info(plugin) -> PluginInfo:
    return PluginInfo(
        name=plugin.name,
        version=plugin.version,
        description=plugin.description,
        author=plugin.author,
        source_url=plugin.source_url,
        installed=plugin.installed,
        enabled=plugin.enabled,
        rating=marketplace.average_rating(plugin),
        rating_count=plugin.rating_count,
    )


@router.get("/plugins", response_model=List[PluginInfo])
def list_plugins(db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)):
    _require_enabled()
    return [_info(p) for p in marketplace.list_plugins(db)]


@router.post("/plugins/{name}/install", response_model=PluginInfo)
def install_plugin(
    name: str, db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)
):
    _require_enabled()
    marketplace.sync_catalog(db)
    plugin = marketplace.install(db, name)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return _info(plugin)


@router.post("/plugins/{name}/uninstall", response_model=PluginInfo)
def uninstall_plugin(
    name: str, db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)
):
    _require_enabled()
    plugin = marketplace.uninstall(db, name)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return _info(plugin)


@router.post("/plugins/{name}/reviews", response_model=PluginInfo)
def review_plugin(
    name: str,
    body: ReviewCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    plugin = marketplace.get_plugin(db, name)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    dbadmin = crud.get_admin(db, admin.username)
    marketplace.add_review(
        db, plugin, dbadmin.id if dbadmin else None, body.rating, body.comment
    )
    return _info(plugin)


@router.get("/plugins/{name}/reviews", response_model=List[ReviewResponse])
def list_reviews(
    name: str, db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)
):
    _require_enabled()
    plugin = marketplace.get_plugin(db, name)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return [
        ReviewResponse(rating=r.rating, comment=r.comment, created_at=r.created_at)
        for r in plugin.reviews
    ]
