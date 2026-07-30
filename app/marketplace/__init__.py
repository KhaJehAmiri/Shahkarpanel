"""Plugin marketplace.

Tracks a catalogue of plugins, their install/enable state, and admin reviews.
A small built-in catalogue (mirroring the bundled plugins) is seeded on first
use; third-party entries can be added to the same table. Installing here means
recording state and metadata — it deliberately does not fetch and execute
remote code (that requires a sandard/signing model out of scope for this phase).
"""
import logging
from typing import List, Optional

from app.db import Session
from app.db.models import MarketplacePlugin, PluginReview

logger = logging.getLogger("uvicorn.error")

# Built-in catalogue. These mirror the bundled plugins in app/plugins/builtin.py.
CATALOG = [
    {
        "name": "event_log",
        "version": "1.0.0",
        "description": "Logs every event on the bus.",
        "author": "shahkar",
        "source_url": "builtin://event_log",
    },
    {
        "name": "node_alert",
        "version": "1.0.0",
        "description": "Warns when a node reports an error.",
        "author": "shahkar",
        "source_url": "builtin://node_alert",
    },
    {
        "name": "auto_heal",
        "version": "1.0.0",
        "description": "Restarts nodes on error/down with a cooldown.",
        "author": "shahkar",
        "source_url": "builtin://auto_heal",
    },
]


def sync_catalog(db: Session) -> int:
    """Ensure built-in catalogue entries exist. Returns number inserted."""
    inserted = 0
    existing = {row[0] for row in db.query(MarketplacePlugin.name).all()}
    for entry in CATALOG:
        if entry["name"] not in existing:
            db.add(MarketplacePlugin(**entry))
            inserted += 1
    if inserted:
        db.commit()
    return inserted


def list_plugins(db: Session) -> List[MarketplacePlugin]:
    sync_catalog(db)
    return db.query(MarketplacePlugin).order_by(MarketplacePlugin.name).all()


def get_plugin(db: Session, name: str) -> Optional[MarketplacePlugin]:
    return db.query(MarketplacePlugin).filter(MarketplacePlugin.name == name).first()


def install(db: Session, name: str, enable: bool = True) -> Optional[MarketplacePlugin]:
    plugin = get_plugin(db, name)
    if plugin is None:
        return None
    plugin.installed = True
    plugin.enabled = enable
    db.commit()
    db.refresh(plugin)
    return plugin


def uninstall(db: Session, name: str) -> Optional[MarketplacePlugin]:
    plugin = get_plugin(db, name)
    if plugin is None:
        return None
    plugin.installed = False
    plugin.enabled = False
    db.commit()
    db.refresh(plugin)
    return plugin


def set_enabled(db: Session, name: str, enabled: bool) -> Optional[MarketplacePlugin]:
    plugin = get_plugin(db, name)
    if plugin is None or not plugin.installed:
        return None
    plugin.enabled = enabled
    db.commit()
    db.refresh(plugin)
    return plugin


def average_rating(plugin: MarketplacePlugin) -> float:
    if not plugin.rating_count:
        return 0.0
    return round(plugin.rating_sum / plugin.rating_count, 2)


def add_review(
    db: Session,
    plugin: MarketplacePlugin,
    admin_id: Optional[int],
    rating: int,
    comment: Optional[str] = None,
) -> PluginReview:
    """Add or replace an admin's review, keeping aggregate counters in sync."""
    rating = max(1, min(5, int(rating)))
    existing = (
        db.query(PluginReview)
        .filter(PluginReview.plugin_id == plugin.id, PluginReview.admin_id == admin_id)
        .first()
    )
    if existing is not None:
        plugin.rating_sum += rating - existing.rating
        existing.rating = rating
        existing.comment = comment
        review = existing
    else:
        review = PluginReview(
            plugin_id=plugin.id, admin_id=admin_id, rating=rating, comment=comment
        )
        db.add(review)
        plugin.rating_sum += rating
        plugin.rating_count += 1
    db.commit()
    db.refresh(review)
    return review


__all__ = [
    "CATALOG",
    "sync_catalog",
    "list_plugins",
    "get_plugin",
    "install",
    "uninstall",
    "set_enabled",
    "average_rating",
    "add_review",
]
