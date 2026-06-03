"""Iran<->foreign tunnels API (phase 6).

CRUD over the ``Tunnel`` model plus a config endpoint that returns the generated
Xray fragments for the relay and exit ends.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app import feature_flags, tunnel as tunnel_svc
from app.db import Session, get_db
from app.db.models import Node, Tunnel
from app.models.admin import Admin
from app.utils import responses

router = APIRouter(
    tags=["Tunnels"],
    prefix="/api/tunnels",
    responses={401: responses._401, 403: responses._403},
)


def _require_enabled():
    if not feature_flags.is_enabled("tunneling"):
        raise HTTPException(status_code=404, detail="Tunneling is disabled")


class TunnelCreate(BaseModel):
    name: str
    relay_node_id: int
    exit_node_id: int
    transport: str = "reality"
    listen_port: int
    target_port: int
    params: Optional[dict] = None


class TunnelUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    transport: Optional[str] = None
    listen_port: Optional[int] = None
    target_port: Optional[int] = None
    params: Optional[dict] = None


class TunnelResponse(BaseModel):
    id: int
    name: str
    enabled: bool
    relay_node_id: int
    exit_node_id: int
    transport: str
    listen_port: int
    target_port: int
    params: Optional[dict] = None
    model_config = ConfigDict(from_attributes=True)


def _get_node(db: Session, node_id: int) -> Node:
    node = db.query(Node).filter(Node.id == node_id).first()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return node


@router.get("", response_model=List[TunnelResponse])
def list_tunnels(db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)):
    _require_enabled()
    return db.query(Tunnel).order_by(Tunnel.id).all()


@router.post("", response_model=TunnelResponse)
def create_tunnel(
    body: TunnelCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    try:
        tunnel_svc.validate_transport(body.transport)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if body.relay_node_id == body.exit_node_id:
        raise HTTPException(status_code=422, detail="relay and exit must be different nodes")
    _get_node(db, body.relay_node_id)
    _get_node(db, body.exit_node_id)

    tunnel = Tunnel(
        name=body.name,
        relay_node_id=body.relay_node_id,
        exit_node_id=body.exit_node_id,
        transport=body.transport,
        listen_port=body.listen_port,
        target_port=body.target_port,
        params=body.params or tunnel_svc.default_params(body.transport),
    )
    db.add(tunnel)
    # Reflect topology roles on the endpoints.
    _get_node(db, body.relay_node_id).role = "relay"
    _get_node(db, body.exit_node_id).role = "exit"
    db.commit()
    db.refresh(tunnel)
    return tunnel


@router.patch("/{tunnel_id}", response_model=TunnelResponse)
def update_tunnel(
    tunnel_id: int,
    body: TunnelUpdate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    tunnel = db.query(Tunnel).filter(Tunnel.id == tunnel_id).first()
    if tunnel is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    if body.transport is not None:
        try:
            tunnel_svc.validate_transport(body.transport)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(tunnel, key, value)
    db.commit()
    db.refresh(tunnel)
    return tunnel


@router.delete("/{tunnel_id}")
def delete_tunnel(
    tunnel_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    tunnel = db.query(Tunnel).filter(Tunnel.id == tunnel_id).first()
    if tunnel is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    db.delete(tunnel)
    db.commit()
    return {}


@router.get("/{tunnel_id}/config")
def tunnel_config(
    tunnel_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Generated Xray fragments for both ends of the tunnel."""
    _require_enabled()
    tunnel = db.query(Tunnel).filter(Tunnel.id == tunnel_id).first()
    if tunnel is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    exit_node = _get_node(db, tunnel.exit_node_id)
    return tunnel_svc.build_tunnel_pair(tunnel, exit_node.address)
