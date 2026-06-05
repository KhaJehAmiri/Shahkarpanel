"""Iran<->foreign tunnels API (phase 6).

CRUD over the ``Tunnel`` model plus config/apply endpoints. Either end of a
tunnel may be a registered node or the panel's own local Xray core: a ``None``
endpoint id means "the panel host is that end". This lets a panel installed in
Iran be the relay (only a foreign exit node added) or a panel abroad be the exit
(only an Iran relay node added).
"""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator

from app import feature_flags, logger, tunnel as tunnel_svc, xray
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
    # None on either end => the panel's own local Xray core is that end.
    relay_node_id: Optional[int] = None
    exit_node_id: Optional[int] = None
    transport: str = "reality"
    listen_port: int
    target_port: int
    params: Optional[dict] = None

    @model_validator(mode="after")
    def _check_ends(self):
        if self.relay_node_id is None and self.exit_node_id is None:
            raise ValueError("at least one end must be a node (both cannot be the panel)")
        if self.relay_node_id is not None and self.relay_node_id == self.exit_node_id:
            raise ValueError("relay and exit must be different nodes")
        return self


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
    relay_node_id: Optional[int] = None
    exit_node_id: Optional[int] = None
    # 'panel' when the end is the local core, otherwise 'node'.
    relay_kind: Literal["panel", "node"] = "node"
    exit_kind: Literal["panel", "node"] = "node"
    transport: str
    listen_port: int
    target_port: int
    params: Optional[dict] = None
    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def of(tunnel: Tunnel) -> "TunnelResponse":
        return TunnelResponse(
            id=tunnel.id,
            name=tunnel.name,
            enabled=tunnel.enabled,
            relay_node_id=tunnel.relay_node_id,
            exit_node_id=tunnel.exit_node_id,
            relay_kind="node" if tunnel.relay_node_id is not None else "panel",
            exit_kind="node" if tunnel.exit_node_id is not None else "panel",
            transport=tunnel.transport,
            listen_port=tunnel.listen_port,
            target_port=tunnel.target_port,
            params=tunnel.params,
        )


def _get_node(db: Session, node_id: int) -> Node:
    node = db.query(Node).filter(Node.id == node_id).first()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return node


def _exit_address(db: Session, exit_node_id: Optional[int]) -> str:
    if exit_node_id is None:
        from config import PANEL_PUBLIC_ADDRESS, UVICORN_HOST
        addr = (PANEL_PUBLIC_ADDRESS or UVICORN_HOST or "").split(":")[0]
        if not addr or addr in ("0.0.0.0", "127.0.0.1"):
            raise HTTPException(
                status_code=422,
                detail="Panel public address is not configured; set PANEL_PUBLIC_ADDRESS to use the panel as a tunnel exit",
            )
        return addr
    return _get_node(db, exit_node_id).address


def _restart_endpoint(db: Session, node_id: Optional[int]):
    """Re-push config to an endpoint so its tunnel fragments take effect."""
    if node_id is None:
        try:
            xray.core.restart(xray.config.include_db_users())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Tunnel apply: failed to restart local core: %s", exc)
        return
    node = xray.nodes.get(node_id)
    if node is not None and getattr(node, "connected", False):
        xray.operations.restart_node(node_id)
    else:
        xray.operations.connect_node(node_id)


@router.get("", response_model=List[TunnelResponse])
def list_tunnels(db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)):
    _require_enabled()
    return [TunnelResponse.of(t) for t in db.query(Tunnel).order_by(Tunnel.id).all()]


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

    if body.relay_node_id is not None:
        _get_node(db, body.relay_node_id)
    if body.exit_node_id is not None:
        _get_node(db, body.exit_node_id)

    params = body.params or tunnel_svc.default_params(body.transport)
    # Generate the Reality keypair now (xray x25519) so the tunnel is usable
    # without a manual key step. No-op for non-reality transports / preset keys.
    if body.transport == "reality":
        tunnel_svc.ensure_reality_keys(params)

    tunnel = Tunnel(
        name=body.name,
        relay_node_id=body.relay_node_id,
        exit_node_id=body.exit_node_id,
        transport=body.transport,
        listen_port=body.listen_port,
        target_port=body.target_port,
        params=params,
    )
    db.add(tunnel)
    # Reflect topology roles on node endpoints (panel endpoints have no row).
    if body.relay_node_id is not None:
        _get_node(db, body.relay_node_id).role = "relay"
    if body.exit_node_id is not None:
        _get_node(db, body.exit_node_id).role = "exit"
    db.commit()
    db.refresh(tunnel)
    return TunnelResponse.of(tunnel)


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
    return TunnelResponse.of(tunnel)


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
    relay_id, exit_id = tunnel.relay_node_id, tunnel.exit_node_id
    db.delete(tunnel)
    # Revert endpoint roles to 'direct' when no other tunnel references them.
    for node_id, role in ((relay_id, "relay"), (exit_id, "exit")):
        if node_id is None:
            continue
        still_used = db.query(Tunnel).filter(
            Tunnel.id != tunnel_id,
            (Tunnel.relay_node_id == node_id) | (Tunnel.exit_node_id == node_id),
        ).first()
        if not still_used:
            node = db.query(Node).filter(Node.id == node_id).first()
            if node is not None and node.role == role:
                node.role = "direct"
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
    exit_addr = _exit_address(db, tunnel.exit_node_id)
    wg_port = (tunnel.params or {}).get("wireguard_port")
    return tunnel_svc.build_tunnel_pair(
        tunnel, exit_addr, wireguard_port=int(wg_port) if wg_port else None
    )


@router.post("/{tunnel_id}/apply")
def apply_tunnel(
    tunnel_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Deploy the tunnel: re-push config to both endpoints so it takes effect."""
    _require_enabled()
    tunnel = db.query(Tunnel).filter(Tunnel.id == tunnel_id).first()
    if tunnel is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    if not tunnel.enabled:
        raise HTTPException(status_code=422, detail="Tunnel is disabled; enable it before applying")

    # Validate the exit is reachable before touching any core.
    _exit_address(db, tunnel.exit_node_id)

    endpoints = {tunnel.relay_node_id, tunnel.exit_node_id}
    for node_id in endpoints:
        _restart_endpoint(db, node_id)

    return {
        "applied": True,
        "relay": "panel" if tunnel.relay_node_id is None else tunnel.relay_node_id,
        "exit": "panel" if tunnel.exit_node_id is None else tunnel.exit_node_id,
    }
