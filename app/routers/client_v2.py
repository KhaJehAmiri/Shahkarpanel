"""SigmaGuard client API (phase A).

Endpoints consumed by the SigmaGuard mobile/desktop app:

* ``POST /api/v2/auth/login``      — end-user login → access + refresh tokens
* ``POST /api/v2/auth/refresh``    — rotate the access token
* ``GET  /api/v2/client/negotiate``— usable protocols for this network + profile
* ``GET  /api/v2/client/config``   — ordered protocols + node hints + sub links
* ``POST /api/v2/client/probe``    — store client ping results, recommend a node

Auth reuses the end-user portal credentials (``portal_enabled`` users). Gated
behind the ``client_api`` feature flag.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app import client as client_engine
from app import dedicated_ip as dedicated_ip_svc
from app import feature_flags
from app.db import Session, crud, get_db
from app.db.models import ClientDevice, ClientProbe, ClientTelemetry, Node, User
from app.login_limit import enforce_login_rate_limit
from app.models.node import NodeStatus
from app.models.user import UserResponse
from app.utils import responses
from app.utils.jwt import (
    app_access_token_expires_in,
    create_app_access_token,
    create_app_refresh_token,
    get_app_payload,
    get_app_refresh_payload,
)
from config import LOGIN_MAX_ATTEMPTS, LOGIN_MAX_WINDOW_SECONDS

router = APIRouter(
    tags=["Client API"],
    prefix="/api/v2",
    responses={401: responses._401, 404: responses._404},
)


def _require_client_api() -> None:
    if not feature_flags.is_enabled("client_api"):
        raise HTTPException(status_code=404, detail="Client API is disabled")


def _available_protocols(db: Session) -> set:
    """Engine protocol names the panel can actually serve right now.

    Derived from the live protocol backends (`app.protocols`) plus node
    inventory, so `negotiate`/`config` never recommend a protocol the backend
    cannot deliver. Mapping from served proxy types to client engine names:

    * vless served      → ``vless-reality`` (+ ``cdn`` via ws behind a CDN)
    * shadowsocks served→ ``shadowsocks-2022``
    * hysteria2 served  → ``hysteria2``
    * a WireGuard node  → ``wireguard`` (and ``amneziawg`` if the node carries
      AmneziaWG obfuscation parameters)
    """
    from app import protocols
    from app.db.models import NodeWireGuard

    served: set = set()
    for backend in protocols.available_backends():
        served.update(backend.protocols)

    avail: set = set()
    if "vless" in served:
        avail.add("vless-reality")
        avail.add("cdn")
    if "shadowsocks" in served and feature_flags.is_enabled("client_ss2022"):
        # SS-2022 needs node-side inbound config + base64 PSK keys (the Xray
        # rpyc account proto can't carry 2022 ciphers). Only advertise it once
        # the operator has provisioned it and flipped the flag.
        avail.add("shadowsocks-2022")
    sb_nodes = crud.get_singbox_nodes(db)
    if sb_nodes:
        if any(n.singbox and n.singbox.hysteria2_enabled for n in sb_nodes):
            avail.add("hysteria2")
        if any(n.singbox and n.singbox.tuic_enabled for n in sb_nodes):
            avail.add("tuic")

    wg_nodes = (
        db.query(Node)
        .filter(Node.core_kind == "wireguard", Node.status != NodeStatus.disabled)
        .all()
    )
    if wg_nodes:
        avail.add("wireguard")
        from app.wireguard.capabilities import node_amnezia_available
        from app.wireguard.sync import awg_params_from_cfg

        for n in wg_nodes:
            if n.wireguard and awg_params_from_cfg(n.wireguard) and node_amnezia_available(n):
                avail.add("amneziawg")
                break

    return avail


def get_current_app_user(request: Request, db: Session = Depends(get_db)) -> User:
    _require_client_api()
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = get_app_payload(auth[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    dbuser = crud.get_user(db, payload["username"])
    if not dbuser or not dbuser.portal_enabled:
        raise HTTPException(status_code=401, detail="App access disabled")
    return dbuser


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class LoginBody(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None


class RefreshBody(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None


@router.post("/auth/login", response_model=TokenResponse)
def app_login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    """Authenticate an end-user and issue app access + refresh tokens."""
    _require_client_api()
    enforce_login_rate_limit(
        request,
        max_attempts=LOGIN_MAX_ATTEMPTS,
        window_seconds=LOGIN_MAX_WINDOW_SECONDS,
    )
    dbuser = crud.verify_portal_user(db, body.username, body.password)
    if not dbuser:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=create_app_access_token(dbuser.username),
        refresh_token=create_app_refresh_token(dbuser.username),
        expires_in=app_access_token_expires_in(),
    )


@router.post("/auth/refresh", response_model=AccessTokenResponse)
def app_refresh(body: RefreshBody, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a fresh access token."""
    _require_client_api()
    payload = get_app_refresh_payload(body.refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    dbuser = crud.get_user(db, payload["username"])
    if not dbuser or not dbuser.portal_enabled:
        raise HTTPException(status_code=401, detail="App access disabled")
    return AccessTokenResponse(
        access_token=create_app_access_token(dbuser.username),
        expires_in=app_access_token_expires_in(),
    )


# --------------------------------------------------------------------------- #
# Negotiate
# --------------------------------------------------------------------------- #
class NegotiateResponse(BaseModel):
    profile: str
    net: str
    udp: bool
    usable_protocols: List[str]
    blocked_protocols: List[str]
    recommended: str


@router.get("/client/negotiate", response_model=NegotiateResponse)
def client_negotiate(
    profile: Optional[str] = Query(None, description="gamer | trader | normal"),
    net: str = Query("open", description="open | restricted | heavily_restricted"),
    udp: bool = Query(True),
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_app_user),
):
    """Ordered list of usable protocols for the current network + profile."""
    effective = client_engine.normalize_profile(profile or dbuser.client_profile)
    available = _available_protocols(db)
    return NegotiateResponse(
        **client_engine.negotiate(profile=effective, net=net, udp=udp, available=available)
    )


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def _active_nodes(db: Session) -> List[dict]:
    rows = (
        db.query(Node)
        .filter(Node.status != NodeStatus.disabled)
        .order_by(Node.id)
        .all()
    )
    return [
        {
            "id": n.id,
            "name": n.name,
            "region": n.region,
            "address": n.address,
            "latency_ms": n.latency_ms,
        }
        for n in rows
    ]


def _v2ray_links(user: UserResponse) -> List[str]:
    try:
        from app.subscription.share import generate_v2ray_links

        return generate_v2ray_links(user.proxies, user.inbounds, user.__dict__, reverse=False)
    except Exception:
        return []


class ProtocolEntry(BaseModel):
    priority: int
    protocol: str
    node_id: Optional[int] = None
    node_name: Optional[str] = None
    region: Optional[str] = None


class ClientConfigResponse(BaseModel):
    profile: str
    country: Optional[str] = None
    net: str
    recommended_protocol: str
    recommended_node: Optional[int] = None
    fallback_node: Optional[int] = None
    protocols: List[ProtocolEntry]
    subscription_url: str = ""
    v2ray_links: List[str] = []
    dedicated_ip: Optional[str] = None


@router.get("/client/config", response_model=ClientConfigResponse)
def client_config(
    profile: Optional[str] = Query(None),
    net: str = Query("open"),
    udp: bool = Query(True),
    country: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_app_user),
):
    """Smart config: ordered protocols + best node + the user's real sub links."""
    effective = client_engine.normalize_profile(profile or dbuser.client_profile)
    available = _available_protocols(db)
    nego = client_engine.negotiate(profile=effective, net=net, udp=udp, available=available)
    nodes = _active_nodes(db)

    # Trader is pinned to the node hosting its dedicated IP (never rotates).
    dedicated = None
    bound_node_id = None
    if effective == "trader":
        dedicated = dedicated_ip_svc.get_for_user(db, dbuser.id)
        bound_node_id = dedicated.node_id if dedicated else None

    selection = client_engine.select_nodes(
        nodes, profile=effective, bound_node_id=bound_node_id
    )

    rec_node_id = selection["recommended_node"]
    rec_node = next((n for n in nodes if n["id"] == rec_node_id), None)

    protocols = [
        ProtocolEntry(
            priority=i + 1,
            protocol=proto,
            node_id=rec_node_id,
            node_name=rec_node["name"] if rec_node else None,
            region=rec_node["region"] if rec_node else None,
        )
        for i, proto in enumerate(nego["usable_protocols"])
    ]

    user = UserResponse.model_validate(dbuser)
    return ClientConfigResponse(
        profile=effective,
        country=country,
        net=nego["net"],
        recommended_protocol=nego["recommended"],
        recommended_node=rec_node_id,
        fallback_node=selection["fallback_node"],
        protocols=protocols,
        subscription_url=getattr(user, "subscription_url", "") or "",
        v2ray_links=_v2ray_links(user),
        dedicated_ip=dedicated.address if dedicated else None,
    )


# --------------------------------------------------------------------------- #
# Probe
# --------------------------------------------------------------------------- #
class ProbeResult(BaseModel):
    node_id: Optional[int] = None
    ping_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    handshake_ms: Optional[float] = None
    protocol_tested: Optional[str] = None


class ProbeBody(BaseModel):
    profile: Optional[str] = None
    results: List[ProbeResult] = []


class ProbeResponse(BaseModel):
    recommended_node: Optional[int] = None
    recommended_protocol: Optional[str] = None
    fallback_node: Optional[int] = None
    fallback_protocol: Optional[str] = None


@router.post("/client/probe", response_model=ProbeResponse)
def client_probe(
    body: ProbeBody,
    net: str = Query("open"),
    udp: bool = Query(True),
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_app_user),
):
    """Persist client ping results and return the best node + protocol."""
    effective = client_engine.normalize_profile(body.profile or dbuser.client_profile)

    for r in body.results:
        db.add(
            ClientProbe(
                user_id=dbuser.id,
                node_id=r.node_id,
                profile=effective,
                protocol=r.protocol_tested,
                ping_ms=r.ping_ms,
                packet_loss_pct=r.packet_loss_pct,
                handshake_ms=r.handshake_ms,
            )
        )
    db.commit()

    nodes = _active_nodes(db)
    probe_dicts = [
        {"node_id": r.node_id, "ping_ms": r.ping_ms, "packet_loss_pct": r.packet_loss_pct}
        for r in body.results
    ]
    selection = client_engine.select_nodes(nodes, profile=effective, probe_results=probe_dicts)
    nego = client_engine.negotiate(
        profile=effective, net=net, udp=udp, available=_available_protocols(db)
    )
    usable = nego["usable_protocols"]

    return ProbeResponse(
        recommended_node=selection["recommended_node"],
        recommended_protocol=usable[0] if usable else None,
        fallback_node=selection["fallback_node"],
        fallback_protocol=usable[1] if len(usable) > 1 else None,
    )


# --------------------------------------------------------------------------- #
# Device token (push)
# --------------------------------------------------------------------------- #
class DeviceTokenBody(BaseModel):
    token: str
    platform: Optional[str] = None
    app_version: Optional[str] = None


@router.post("/client/device-token", status_code=204)
def register_device_token(
    body: DeviceTokenBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_app_user),
):
    """Register/refresh an FCM/APNs token for push notifications (upsert)."""
    if not body.token.strip():
        raise HTTPException(status_code=422, detail="token is required")
    device = db.query(ClientDevice).filter(ClientDevice.token == body.token).first()
    if device:
        device.user_id = dbuser.id
        device.platform = body.platform
        device.app_version = body.app_version
        device.updated_at = datetime.utcnow()
    else:
        db.add(
            ClientDevice(
                user_id=dbuser.id,
                token=body.token,
                platform=body.platform,
                app_version=body.app_version,
            )
        )
    db.commit()


@router.delete("/client/device-token", status_code=204)
def delete_device_token(
    token: str = Query(...),
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_app_user),
):
    """Unregister a device token (e.g. on logout)."""
    db.query(ClientDevice).filter(
        ClientDevice.token == token, ClientDevice.user_id == dbuser.id
    ).delete()
    db.commit()


# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #
class TelemetryBody(BaseModel):
    session_id: Optional[str] = None
    active_protocol: Optional[str] = None
    active_node: Optional[int] = None
    ping_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    bytes_sent: Optional[int] = None
    bytes_recv: Optional[int] = None


@router.post("/client/telemetry", status_code=204)
def client_telemetry(
    body: TelemetryBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_app_user),
):
    """Ingest a per-session network-quality sample from the app."""
    db.add(
        ClientTelemetry(
            user_id=dbuser.id,
            session_id=body.session_id,
            active_protocol=body.active_protocol,
            active_node=body.active_node,
            ping_ms=body.ping_ms,
            packet_loss_pct=body.packet_loss_pct,
            bytes_sent=body.bytes_sent,
            bytes_recv=body.bytes_recv,
        )
    )
    db.commit()


# --------------------------------------------------------------------------- #
# Dedicated IP (Trader)
# --------------------------------------------------------------------------- #
class DedicatedIPResponse(BaseModel):
    address: Optional[str] = None
    node_id: Optional[int] = None
    assigned: bool = False


@router.get("/client/dedicated-ip", response_model=DedicatedIPResponse)
def client_dedicated_ip(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_current_app_user),
):
    """The Trader's pinned static IP (to whitelist on exchanges), if any."""
    ip = dedicated_ip_svc.get_for_user(db, dbuser.id)
    if not ip:
        return DedicatedIPResponse(assigned=False)
    return DedicatedIPResponse(address=ip.address, node_id=ip.node_id, assigned=True)
