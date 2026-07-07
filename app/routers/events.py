"""Audit log API — read durable events from the ``events`` table."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.db import Session, get_db
from app.db.models import Event
from app.models.admin import Admin
from app.rbac import require_permission
from app.utils import responses

router = APIRouter(
    tags=["Audit"],
    prefix="/api/events",
    responses={401: responses._401, 403: responses._403},
)


class EventResponse(BaseModel):
    id: int
    type: str
    payload: Optional[dict] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=List[EventResponse])
def list_events(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    event_type: Optional[str] = Query(None, alias="type"),
    db: Session = Depends(get_db),
    _: Admin = Depends(require_permission("system:read")),
):
    """Paginated audit log of panel events."""
    q = db.query(Event).order_by(Event.id.desc())
    if event_type:
        q = q.filter(Event.type == event_type)
    return q.offset(offset).limit(limit).all()
