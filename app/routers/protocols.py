from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import protocols
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["Protocols"],
    prefix="/api/protocols",
    responses={401: responses._401, 403: responses._403},
)


class ProtocolBackendInfo(BaseModel):
    name: str
    available: bool
    protocols: List[str]
    transports: List[str]
    description: str


@router.get("", response_model=List[ProtocolBackendInfo])
def list_backends(_: Admin = Depends(Admin.get_current)):
    """List protocol backends and their capabilities (multi-protocol abstraction)."""
    return [b.capability() for b in protocols.all_backends()]
