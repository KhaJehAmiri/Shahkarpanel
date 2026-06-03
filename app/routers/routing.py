from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import feature_flags, routing
from app.db import Session, get_db
from app.models.admin import Admin
from app.utils import responses
from config import ROUTING_STRATEGY

router = APIRouter(
    tags=["Routing"],
    prefix="/api/routing",
    responses={401: responses._401, 403: responses._403},
)


class RoutedNode(BaseModel):
    id: int
    name: str
    region: Optional[str] = None
    latency_ms: Optional[float] = None
    capacity: Optional[int] = None
    status: str


def _require_enabled():
    if not feature_flags.is_enabled("smart_routing"):
        raise HTTPException(status_code=404, detail="Smart routing is disabled")


@router.get("/strategies", response_model=List[str])
def list_strategies(_: Admin = Depends(Admin.get_current)):
    _require_enabled()
    return routing.available_strategies()


@router.get("/nodes", response_model=List[RoutedNode])
def order_nodes(
    strategy: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.get_current),
):
    """Return nodes ordered best-first for the given strategy/region."""
    _require_enabled()
    from app.db.models import Node

    nodes = db.query(Node).all()
    ordered = routing.select_nodes(
        nodes, strategy=strategy or ROUTING_STRATEGY, region=region, limit=limit
    )
    return [
        RoutedNode(
            id=n.id,
            name=n.name,
            region=n.region,
            latency_ms=n.latency_ms,
            capacity=n.capacity,
            status=n.status.value if hasattr(n.status, "value") else str(n.status),
        )
        for n in ordered
    ]
