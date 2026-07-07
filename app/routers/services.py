"""REST API for the centralized service catalog and per-node enablement."""
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import crud, get_db
from app.models.admin import Admin
from app.models.node import NodeResponse
from app.utils import responses

router = APIRouter(tags=["Services"], prefix="/api")


class PanelServiceResponse(BaseModel):
    slug: str
    display_name: str
    engine: str
    protocol: str
    config: dict = Field(default_factory=dict)
    sort_order: int = 0


class NodeServiceBindingResponse(BaseModel):
    service_slug: str
    display_name: str
    engine: str
    protocol: str
    enabled: bool
    overrides: Optional[dict] = None


class NodeServicesUpdate(BaseModel):
    enabled: List[str] = Field(..., description="Service slugs to enable on this node")


@router.get("/services", response_model=List[PanelServiceResponse])
def list_panel_services(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Master service catalog (define once)."""
    crud.seed_panel_services(db)
    rows = crud.get_panel_services(db)
    return [
        PanelServiceResponse(
            slug=r.slug,
            display_name=r.display_name,
            engine=r.engine,
            protocol=r.protocol,
            config=r.config or {},
            sort_order=r.sort_order or 0,
        )
        for r in rows
    ]


@router.get("/node/{node_id}/services", response_model=List[NodeServiceBindingResponse])
def get_node_services(
    node_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    dbnode = crud.get_node_by_id(db, node_id)
    if not dbnode:
        raise HTTPException(status_code=404, detail="Node not found")
    crud.seed_panel_services(db)
    catalog = {s.slug: s for s in crud.get_panel_services(db)}
    bindings = {b.service_slug: b for b in crud.get_node_service_bindings(db, node_id)}
    out: List[NodeServiceBindingResponse] = []
    for slug, svc in catalog.items():
        b = bindings.get(slug)
        out.append(
            NodeServiceBindingResponse(
                service_slug=slug,
                display_name=svc.display_name,
                engine=svc.engine,
                protocol=svc.protocol,
                enabled=bool(b and b.enabled),
                overrides=b.overrides if b else None,
            )
        )
    return out


def _apply_node_services_task(node_id: int) -> None:
    from app.services.node_apply import apply_node_services

    apply_node_services(node_id)


@router.put("/node/{node_id}/services", response_model=NodeResponse, responses={404: responses._404})
def update_node_services(
    node_id: int,
    body: NodeServicesUpdate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Enable catalog services on a node, materialize config, and push to agent."""
    dbnode = crud.get_node_by_id(db, node_id)
    if not dbnode:
        raise HTTPException(status_code=404, detail="Node not found")

    from app.services.node_apply import set_node_services

    set_node_services(db, dbnode, body.enabled, replace=True)
    db.refresh(dbnode)
    bg.add_task(_apply_node_services_task, node_id)
    return dbnode
