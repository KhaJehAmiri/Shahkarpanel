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
    intermediate_node_id: Optional[int] = None
    intermediate_port: Optional[int] = None
    exit_node_id: Optional[int] = None
    transport: str = "reality"
    listen_port: int
    target_port: int
    params: Optional[dict] = None
    template_id: Optional[str] = None

    @model_validator(mode="after")
    def _check_ends(self):
        if self.template_id:
            from app.tunnel.templates import get_template, requires_intermediate, template_hops

            try:
                spec = get_template(self.template_id)
            except KeyError as exc:
                raise ValueError(f"unknown tunnel template: {self.template_id!r}") from exc
            if spec.get("transport"):
                self.transport = spec["transport"]
            if self.params is None and spec.get("params") is not None:
                self.params = dict(spec["params"])
            hops = template_hops(spec)
            if requires_intermediate(spec) and self.intermediate_node_id is None:
                raise ValueError("template requires intermediate_node_id (3-hop chain)")

        node_ids = [
            nid for nid in (self.relay_node_id, self.intermediate_node_id, self.exit_node_id)
            if nid is not None
        ]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("relay, transit, and exit must be different nodes")
        if self.relay_node_id is None and self.exit_node_id is None and self.intermediate_node_id is None:
            raise ValueError("at least one end must be a node (all cannot be the panel)")
        if self.relay_node_id is None and self.exit_node_id is None:
            raise ValueError("at least one of relay or exit must be a node")
        if self.intermediate_node_id is not None and self.intermediate_port is None:
            self.intermediate_port = max(self.target_port - 1, 1025)
        return self


class TunnelUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    intermediate_node_id: Optional[int] = None
    intermediate_port: Optional[int] = None
    transport: Optional[str] = None
    listen_port: Optional[int] = None
    target_port: Optional[int] = None
    params: Optional[dict] = None


class TunnelResponse(BaseModel):
    id: int
    name: str
    enabled: bool
    relay_node_id: Optional[int] = None
    intermediate_node_id: Optional[int] = None
    intermediate_port: Optional[int] = None
    exit_node_id: Optional[int] = None
    hops: int = 2
    # 'panel' when the end is the local core, otherwise 'node'.
    relay_kind: Literal["panel", "node"] = "node"
    exit_kind: Literal["panel", "node"] = "node"
    transport: str
    listen_port: int
    target_port: int
    params: Optional[dict] = None
    # Result of the auto-apply that ran after create/update (None if not run).
    auto_apply: Optional[dict] = None
    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def of(tunnel: Tunnel, auto_apply: Optional[dict] = None) -> "TunnelResponse":
        return TunnelResponse(
            id=tunnel.id,
            name=tunnel.name,
            enabled=tunnel.enabled,
            relay_node_id=tunnel.relay_node_id,
            intermediate_node_id=tunnel.intermediate_node_id,
            intermediate_port=tunnel.intermediate_port,
            exit_node_id=tunnel.exit_node_id,
            hops=tunnel_svc.tunnel_hops(tunnel),
            relay_kind="node" if tunnel.relay_node_id is not None else "panel",
            exit_kind="node" if tunnel.exit_node_id is not None else "panel",
            transport=tunnel.transport,
            listen_port=tunnel.listen_port,
            target_port=tunnel.target_port,
            params=tunnel.params,
            auto_apply=auto_apply,
        )


def _get_node(db: Session, node_id: int) -> Node:
    node = db.query(Node).filter(Node.id == node_id).first()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return node


def _reserved_panel_ports() -> set[int]:
    try:
        from app.xray.inbound_ports import PANEL_SERVICE_HINTS

        return set(PANEL_SERVICE_HINTS)
    except Exception:  # pragma: no cover - defensive
        return {80, 443, 8000}


def _guard_panel_ports(exit_node_id, target_port) -> None:
    """Reject a tunnel whose panel-local exit inbound would collide with the
    panel's own web/API port — otherwise Xray refuses the whole config and the
    panel core (all proxy inbounds) goes down."""
    if exit_node_id is None and target_port in _reserved_panel_ports():
        raise HTTPException(
            status_code=422,
            detail=(
                f"target_port {target_port} is reserved by the panel web/API server. "
                "Choose a different port (e.g. 8443) for a panel-hosted exit, or use "
                "a dedicated node as the exit."
            ),
        )


def _exit_address(db: Session, exit_node_id: Optional[int]) -> str:
    if exit_node_id is None:
        from config import PANEL_PUBLIC_ADDRESS, UVICORN_HOST
        from app.tunnel import clean_public_host
        addr = clean_public_host(PANEL_PUBLIC_ADDRESS or UVICORN_HOST or "")
        if not addr or addr in ("0.0.0.0", "127.0.0.1"):
            raise HTTPException(
                status_code=422,
                detail="Panel public address is not configured; set PANEL_PUBLIC_ADDRESS to use the panel as a tunnel exit",
            )
        return addr
    return _get_node(db, exit_node_id).address


def _sync_tunnel_node_roles(db: Session, tunnel: Tunnel) -> None:
    """Reflect relay/transit/exit roles on node endpoints when a tunnel is enabled."""
    role_map = (
        (tunnel.relay_node_id, "relay"),
        (tunnel.intermediate_node_id, "transit"),
        (tunnel.exit_node_id, "exit"),
    )
    for node_id, role in role_map:
        if node_id is None:
            continue
        node = db.query(Node).filter(Node.id == node_id).first()
        if node is not None and tunnel.enabled:
            node.role = role


def _revert_unused_node_roles(
    db: Session,
    tunnel_id: int,
    relay_id,
    exit_id,
    intermediate_id=None,
) -> None:
    for node_id, role in (
        (relay_id, "relay"),
        (intermediate_id, "transit"),
        (exit_id, "exit"),
    ):
        if node_id is None:
            continue
        still_used = db.query(Tunnel).filter(
            Tunnel.id != tunnel_id,
            Tunnel.enabled.is_(True),
            (
                (Tunnel.relay_node_id == node_id)
                | (Tunnel.exit_node_id == node_id)
                | (Tunnel.intermediate_node_id == node_id)
            ),
        ).first()
        if not still_used:
            node = db.query(Node).filter(Node.id == node_id).first()
            if node is not None and node.role == role:
                node.role = "direct"


def _node_endpoint_state(db: Session, node_id: int) -> tuple[bool, object | None]:
    """Live RPyC session wins; API-only overlays Postgres ``nodes.status``.

    The HTTP process has ``xray.nodes == {}``, so dashboard health used to
    report every hop disconnected even when the worker already had them
    connected and the exit listen port was answering TCP.
    """
    live = None
    try:
        live = xray.nodes.get(node_id)
    except Exception:
        live = None
    if live is not None:
        return bool(getattr(live, "connected", False)), live
    row = db.query(Node).filter(Node.id == int(node_id)).first()
    if row is None:
        return False, None
    status = getattr(row.status, "value", row.status)
    return str(status or "") == "connected", None


def _restart_endpoint(db: Session, node_id: Optional[int]):
    """Re-push config to an endpoint so its tunnel fragments take effect."""
    if node_id is None:
        from app.runtime_role import delegate_to_worker

        if delegate_to_worker("restart_core"):
            return
        try:
            xray.core.restart(xray.config.include_db_users())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Tunnel apply: failed to restart local core: %s", exc)
        return

    from app.db import crud
    from app.singbox.operations import sync_node as singbox_sync_node
    from app.tunnel.relay import ensure_tunnel_wireguard_port
    from app.wireguard.operations import sync_node as wg_sync_node

    dbnode = crud.get_node_by_id(db, node_id)
    if dbnode is not None:
        for t in db.query(Tunnel).filter(
            Tunnel.enabled.is_(True),
            Tunnel.relay_node_id == node_id,
        ).all():
            if ensure_tunnel_wireguard_port(db, t):
                db.commit()
        try:
            wg_sync_node(db, dbnode)
        except Exception as exc:
            logger.warning("Tunnel apply: WireGuard sync on node %s failed: %s", node_id, exc)
        try:
            singbox_sync_node(db, dbnode)
        except Exception as exc:
            logger.warning("Tunnel apply: sing-box sync on node %s failed: %s", node_id, exc)

    node = xray.nodes.get(node_id)
    if node is not None and getattr(node, "connected", False):
        xray.operations.restart_node(node_id)
    else:
        xray.operations.connect_node(node_id)


def _wait_endpoint_ready(db: Session, node_id: Optional[int], *, timeout: float = 45.0) -> bool:
    """Wait for async connect/restart to finish so health is not checked too early."""
    import time

    from app.runtime_role import owns_control_plane

    if not owns_control_plane():
        return False

    if node_id is None:
        deadline = time.time() + min(timeout, 15.0)
        while time.time() < deadline:
            if getattr(xray.core, "started", False):
                return True
            time.sleep(0.4)
        return bool(getattr(xray.core, "started", False))

    from app.tunnel.relay import node_delegates_wireguard_to_tunnel

    delegates = False
    try:
        delegates = node_delegates_wireguard_to_tunnel(db, int(node_id))
    except Exception:
        delegates = False

    deadline = time.time() + timeout
    while time.time() < deadline:
        node = xray.nodes.get(node_id)
        if node is not None and getattr(node, "connected", False):
            if not delegates or bool(getattr(node, "wg_tunnel_capture_active", False)):
                return True
        time.sleep(0.5)
    return False


def _tcp_reachable(address: str, port: int, timeout: float = 3.0) -> bool:
    """Best-effort TCP connect probe used for post-apply health-checks."""
    import socket

    try:
        with socket.create_connection((address, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _tunnel_health(db: Session, tunnel: Tunnel) -> dict:
    """Verify both ends look alive after an apply.

    - node endpoints must be connected in the live xray registry (worker),
      or ``nodes.status=connected`` in Postgres when this process has no
      sessions (API);
    - the relay must be able to reach the exit's tunnel ``target_port``
      (the exit inbound binds there — not ``listen_port``).
    """
    checks: dict = {}

    for label, node_id in (
        ("relay", tunnel.relay_node_id),
        ("transit", tunnel.intermediate_node_id),
        ("exit", tunnel.exit_node_id),
    ):
        if node_id is None:
            if label == "transit":
                continue
            checks[label] = {"kind": "panel", "connected": True}
        else:
            connected, live = _node_endpoint_state(db, node_id)
            entry = {
                "kind": "node",
                "node_id": node_id,
                "connected": connected,
            }
            # Relays that delegate WG into dokodemo must still have capture up.
            # Without this, keep-live / native fallback leaves health "green"
            # while the Reality hop is actually dead until manual Apply.
            # Capture is only knowable from the worker's live session — on the
            # API, missing capture must not flip the hop to down.
            if label == "relay" and connected and live is not None:
                try:
                    from app.tunnel.relay import node_delegates_wireguard_to_tunnel

                    if node_delegates_wireguard_to_tunnel(db, int(node_id)):
                        capture = bool(getattr(live, "wg_tunnel_capture_active", False))
                        entry["capture_active"] = capture
                        if not capture:
                            entry["tunnel_ready"] = False
                except Exception:
                    pass
            checks[label] = entry

    if tunnel.intermediate_node_id:
        try:
            transit_addr = _get_node(db, tunnel.intermediate_node_id).address
            transit_port = tunnel.intermediate_port or tunnel_svc.transit_port(tunnel)
            checks["transit_listen"] = {
                "address": transit_addr,
                "port": transit_port,
                "reachable": _tcp_reachable(transit_addr, transit_port),
            }
        except HTTPException as exc:
            checks["transit_listen"] = {"reachable": False, "error": exc.detail}

    try:
        exit_addr = _exit_address(db, tunnel.exit_node_id)
        # Exit inbound always listens on target_port (see build_exit_inbound).
        probe_port = int(tunnel.target_port)
        reachable = _tcp_reachable(exit_addr, probe_port)
        checks["exit_listen"] = {
            "address": exit_addr,
            "port": probe_port,
            "reachable": reachable,
        }
    except HTTPException as exc:
        checks["exit_listen"] = {"reachable": False, "error": exc.detail}

    healthy = all(
        c.get("connected", True) for c in checks.values() if "connected" in c
    ) and checks.get("exit_listen", {}).get("reachable", False)
    if tunnel.intermediate_node_id:
        healthy = healthy and checks.get("transit_listen", {}).get("reachable", False)
    healthy = healthy and all(
        c.get("tunnel_ready", True) for c in checks.values()
    )
    return {"healthy": healthy, "checks": checks}


def _apply_tunnel(db: Session, tunnel: Tunnel, health: bool = True) -> dict:
    """Re-push config to both endpoints and (optionally) health-check the path."""
    from app.tunnel.relay import ensure_tunnel_wireguard_port

    if ensure_tunnel_wireguard_port(db, tunnel):
        db.commit()
        db.refresh(tunnel)
    _exit_address(db, tunnel.exit_node_id)  # validate reachability first
    from app.runtime_role import delegate_to_worker

    if delegate_to_worker("apply_tunnel", str(int(tunnel.id))):
        result = {
            "applied": "pending",
            "hops": tunnel_svc.tunnel_hops(tunnel),
            "relay": "panel" if tunnel.relay_node_id is None else tunnel.relay_node_id,
            "transit": tunnel.intermediate_node_id,
            "exit": "panel" if tunnel.exit_node_id is None else tunnel.exit_node_id,
        }
        if health:
            result["health"] = _tunnel_health(db, tunnel)
        return result
    # Exit (and transit) must be listening before the relay dials them —
    # especially important for node→node where there is no panel core in between.
    # ``intermediate_node_id is None`` means "no transit", NOT "panel is transit".
    ordered_ends: list = []
    for node_id, panel_end in (
        (tunnel.exit_node_id, tunnel.exit_node_id is None),
        (tunnel.intermediate_node_id, False),
        (tunnel.relay_node_id, tunnel.relay_node_id is None),
    ):
        if node_id is None and not panel_end:
            continue
        if node_id is None:
            if None not in ordered_ends:
                ordered_ends.append(None)
        elif node_id not in ordered_ends:
            ordered_ends.append(node_id)
    for node_id in ordered_ends:
        _restart_endpoint(db, node_id)
        # connect_node/restart_node are fire-and-forget threads — wait so the
        # subsequent health check (and auto-heal) see the real capture state.
        _wait_endpoint_ready(db, node_id)

    if tunnel.exit_node_id is None and (tunnel.params or {}).get("wireguard_port"):
        from app.wireguard.host_sync import sync_panel_exit_wireguard

        sync_panel_exit_wireguard(db)

    from app.tunnel.relay import clear_tunnel_relay_cache

    clear_tunnel_relay_cache()

    result = {
        "applied": True,
        "hops": tunnel_svc.tunnel_hops(tunnel),
        "relay": "panel" if tunnel.relay_node_id is None else tunnel.relay_node_id,
        "transit": tunnel.intermediate_node_id,
        "exit": "panel" if tunnel.exit_node_id is None else tunnel.exit_node_id,
    }
    if health:
        result["health"] = _tunnel_health(db, tunnel)
    return result


def _auto_apply(db: Session, tunnel: Tunnel) -> Optional[dict]:
    """Apply a tunnel right after create/update, swallowing failures.

    Auto-apply is a convenience: a failure here must not fail the CRUD call, so
    we log and return the error for the client to surface instead of raising.
    """
    if not tunnel.enabled:
        return None
    try:
        return _apply_tunnel(db, tunnel, health=False)
    except HTTPException as exc:
        logger.warning("Tunnel %s auto-apply skipped: %s", tunnel.id, exc.detail)
        return {"applied": False, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Tunnel %s auto-apply failed: %s", tunnel.id, exc)
        return {"applied": False, "detail": str(exc)}


@router.get("/transports")
def tunnel_transports(_: Admin = Depends(Admin.check_sudo_admin)):
    """Supported tunnel transports with engine metadata (xray vs sing-box stub)."""
    _require_enabled()
    return {
        "transports": [
            {"id": tid, **meta}
            for tid, meta in tunnel_svc.TUNNEL_TRANSPORT_META.items()
        ]
    }


@router.get("/templates")
def tunnel_templates(_: Admin = Depends(Admin.check_sudo_admin)):
    """Country-pair and multi-hop tunnel presets."""
    _require_enabled()
    from app.tunnel.templates import iran_pair_templates, serialize_template, TUNNEL_TEMPLATES

    templates = {
        tid: serialize_template(tid, spec)
        for tid, spec in TUNNEL_TEMPLATES.items()
    }
    return {"templates": templates, "iran_pairs": iran_pair_templates()}


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

    _guard_panel_ports(body.exit_node_id, body.target_port)

    if body.relay_node_id is not None:
        _get_node(db, body.relay_node_id)
    if body.intermediate_node_id is not None:
        _get_node(db, body.intermediate_node_id)
    if body.exit_node_id is not None:
        _get_node(db, body.exit_node_id)

    if body.template_id:
        from app.tunnel.templates import get_template, region_matches

        spec = get_template(body.template_id)
        relay_r = spec.get("relay_region")
        exit_r = spec.get("exit_region")
        # Region presets are UI hints. Never reject an explicit node→node
        # selection — operators often tag foreign boxes as uk/eu/de loosely,
        # and blocking create made "node to node" look broken.
        if relay_r and body.relay_node_id is not None:
            relay_node = _get_node(db, body.relay_node_id)
            if not region_matches(relay_r, relay_node.region):
                logger.warning(
                    "Tunnel create: relay node %s region %r does not match "
                    "template preset %r (allowed for node→node)",
                    body.relay_node_id,
                    relay_node.region,
                    relay_r,
                )
        if exit_r and body.exit_node_id is not None:
            exit_node = _get_node(db, body.exit_node_id)
            if not region_matches(exit_r, exit_node.region):
                logger.warning(
                    "Tunnel create: exit node %s region %r does not match "
                    "template preset %r (allowed for node→node)",
                    body.exit_node_id,
                    exit_node.region,
                    exit_r,
                )

    params = body.params or tunnel_svc.default_params(body.transport)
    if body.transport == "reality":
        tunnel_svc.ensure_reality_keys(params)
    elif body.transport == "quic":
        tunnel_svc.ensure_quic_key(params)
    elif tunnel_svc.transport_engine(body.transport) == "singbox":
        tunnel_svc.ensure_singbox_tunnel_secrets(params, body.transport)

    tunnel = Tunnel(
        name=body.name,
        relay_node_id=body.relay_node_id,
        intermediate_node_id=body.intermediate_node_id,
        intermediate_port=body.intermediate_port,
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
    if body.intermediate_node_id is not None:
        _get_node(db, body.intermediate_node_id).role = "transit"
    if body.exit_node_id is not None:
        _get_node(db, body.exit_node_id).role = "exit"
    db.commit()
    db.refresh(tunnel)
    applied = _auto_apply(db, tunnel)
    return TunnelResponse.of(tunnel, auto_apply=applied)


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
    prev_relay, prev_exit = tunnel.relay_node_id, tunnel.exit_node_id
    prev_intermediate = tunnel.intermediate_node_id
    prev_enabled = tunnel.enabled
    if body.transport is not None:
        try:
            tunnel_svc.validate_transport(body.transport)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(tunnel, key, value)
    _guard_panel_ports(tunnel.exit_node_id, tunnel.target_port)
    if not tunnel.enabled and prev_enabled:
        _revert_unused_node_roles(db, tunnel.id, prev_relay, prev_exit, prev_intermediate)
    elif tunnel.enabled:
        _sync_tunnel_node_roles(db, tunnel)
    db.commit()
    db.refresh(tunnel)
    applied = _auto_apply(db, tunnel)
    return TunnelResponse.of(tunnel, auto_apply=applied)


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
    intermediate_id = tunnel.intermediate_node_id
    db.delete(tunnel)
    _revert_unused_node_roles(db, tunnel_id, relay_id, exit_id, intermediate_id)
    # Legacy revert (disabled-only tunnels): kept for backwards compatibility.
    for node_id, role in ((relay_id, "relay"), (intermediate_id, "transit"), (exit_id, "exit")):
        if node_id is None:
            continue
        still_used = db.query(Tunnel).filter(
            (Tunnel.relay_node_id == node_id)
            | (Tunnel.exit_node_id == node_id)
            | (Tunnel.intermediate_node_id == node_id),
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
    intermediate_addr = None
    if tunnel.intermediate_node_id is not None:
        intermediate_addr = _get_node(db, tunnel.intermediate_node_id).address
    wg_port = (tunnel.params or {}).get("wireguard_port")
    return tunnel_svc.build_tunnel_pair(
        tunnel,
        exit_addr,
        intermediate_address=intermediate_addr,
        wireguard_port=int(wg_port) if wg_port else None,
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

    return _apply_tunnel(db, tunnel, health=True)


@router.get("/{tunnel_id}/health")
def tunnel_health(
    tunnel_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Re-check relay/exit connectivity for a tunnel without re-pushing config."""
    _require_enabled()
    tunnel = db.query(Tunnel).filter(Tunnel.id == tunnel_id).first()
    if tunnel is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    return _tunnel_health(db, tunnel)
