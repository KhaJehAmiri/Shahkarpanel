"""Shared node registration logic for bootstrap and manual add."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app import xray
from app.db import crud
from app.models.node import CoreKind, NodeCreate


def finalize_new_node(
    db: Session,
    dbnode,
    *,
    wireguard_defaults: bool = True,
) -> None:
    """Apply post-create defaults shared by bootstrap and manual registration."""
    if wireguard_defaults and getattr(dbnode, "core_kind", None) == CoreKind.wireguard.value:
        crud.provision_wireguard_defaults(db, dbnode)


def connect_node_async(bg, node_id: int) -> None:
    bg.add_task(xray.operations.connect_node, node_id=node_id)


def create_node_record(db: Session, spec: NodeCreate):
    return crud.create_node(db, spec)


def apply_bootstrap_metadata(
    db: Session,
    dbnode,
    *,
    tenant_id: Optional[int] = None,
    role: Optional[str] = None,
    address: Optional[str] = None,
) -> None:
    if address:
        dbnode.provision_host = address
    if tenant_id is not None:
        dbnode.tenant_id = tenant_id
    if role:
        dbnode.role = role
    dbnode.provision_status = "registered"
    db.commit()
    db.refresh(dbnode)
