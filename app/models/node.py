from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class NodeStatus(str, Enum):
    connected = "connected"
    connecting = "connecting"
    error = "error"
    disabled = "disabled"


class CoreKind(str, Enum):
    """Which traffic core a node runs.

    ``xray`` nodes are driven over the rpyc/REST Xray agent; ``wireguard``
    nodes run native WireGuard and are driven over the ``/wg/*`` agent
    endpoints. Usage from either feeds the single central ``used_traffic``.
    """

    xray = "xray"
    wireguard = "wireguard"


class NodeSingBoxConfig(BaseModel):
    """Per-node sing-box server config (Hysteria2 / TUIC on a normal Xray node)."""

    certificate_path: Optional[str] = None
    key_path: Optional[str] = None
    sni: Optional[str] = None
    clash_api_port: int = 9095
    clash_api_secret: Optional[str] = None
    hysteria2_enabled: bool = False
    hysteria2_port: Optional[int] = None
    hysteria2_up_mbps: Optional[int] = None
    hysteria2_down_mbps: Optional[int] = None
    hysteria2_obfs_password: Optional[str] = None
    tuic_enabled: bool = False
    tuic_port: Optional[int] = None
    tuic_congestion_control: str = "bbr"
    anytls_enabled: bool = False
    anytls_port: Optional[int] = None
    tls_trusted: bool = False
    tls_issuer: Optional[str] = None
    tls_expires_at: Optional[datetime] = None
    tls_le_domain: Optional[str] = None
    tls_le_kind: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class NodeWireGuardConfig(BaseModel):
    """Per-node native WireGuard server configuration."""

    interface: str = "wg0"
    listen_port: int = Field(default=51820, gt=0, lt=65536)
    subnet: str = "10.10.0.0/16"
    interface_host: Optional[str] = None
    public_key: Optional[str] = None
    endpoint: Optional[str] = None
    mtu: int = Field(default=1420, gt=0)
    dns: Optional[str] = None
    plain_enabled: bool = True
    awg_enabled: bool = False
    awg_interface: str = "wg1"
    awg_listen_port: int = Field(default=51821, gt=0, lt=65536)
    awg_subnet: str = "10.11.0.0/16"
    awg_interface_host: Optional[str] = None
    awg_public_key: Optional[str] = None
    awg_endpoint: Optional[str] = None
    # AmneziaWG obfuscation params for the awg listener.
    awg_jc: Optional[int] = None
    awg_jmin: Optional[int] = None
    awg_jmax: Optional[int] = None
    awg_s1: Optional[int] = None
    awg_s2: Optional[int] = None
    awg_h1: Optional[int] = None
    awg_h2: Optional[int] = None
    awg_h3: Optional[int] = None
    awg_h4: Optional[int] = None
    awg_s3: Optional[int] = None
    awg_s4: Optional[int] = None
    sg_wire_enabled: bool = False
    sg_wire_preset_rev: Optional[str] = None
    direct_listen_port: Optional[int] = None
    xray_wg_enabled: bool = False
    xray_wg_listen_port: Optional[int] = None
    xray_wg_mtu: int = 1420
    xray_wg_noise: Optional[dict] = None
    model_config = ConfigDict(from_attributes=True)


class NodeSettings(BaseModel):
    min_node_version: str = "v0.2.0"
    certificate: str


class Node(BaseModel):
    name: str
    address: str
    port: int = 62050
    api_port: int = 62051
    usage_coefficient: float = Field(gt=0, default=1.0)
    region: Optional[str] = None
    capacity: Optional[int] = None
    group_id: Optional[int] = None
    core_kind: CoreKind = CoreKind.xray
    # Per-node Cloudflare WARP exit (Xray nodes).
    warp_enabled: bool = False
    warp_tag: Optional[str] = None
    # ``full`` = all traffic via WARP; ``sensitive`` = Google/YouTube/AI only.
    warp_mode: str = "full"


class NodeCreate(Node):
    add_as_new_host: bool = True
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "DE node",
            "address": "192.168.1.1",
            "port": 62050,
            "api_port": 62051,
            "add_as_new_host": True,
            "usage_coefficient": 1
        }
    })


class NodeModify(Node):
    name: Optional[str] = Field(None, nullable=True)
    address: Optional[str] = Field(None, nullable=True)
    port: Optional[int] = Field(None, nullable=True)
    api_port: Optional[int] = Field(None, nullable=True)
    status: Optional[NodeStatus] = Field(None, nullable=True)
    usage_coefficient: Optional[float] = Field(None, nullable=True)
    core_kind: Optional[CoreKind] = Field(None, nullable=True)
    warp_enabled: Optional[bool] = Field(None, nullable=True)
    warp_tag: Optional[str] = Field(None, nullable=True)
    warp_mode: Optional[str] = Field(None, nullable=True)
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "DE node",
            "address": "192.168.1.1",
            "port": 62050,
            "api_port": 62051,
            "status": "disabled",
            "usage_coefficient": 1.0
        }
    })


class NodeWarpSettings(BaseModel):
    """Toggle Cloudflare WARP exit policy for this node.

    - ``mode=full``: all protocols exit via WARP (legacy).
    - ``mode=sensitive``: only Google / YouTube / AI domains exit via WARP;
      other traffic stays DIRECT. Same client configs — no new links.
    - ``tag`` may be comma-separated (``warp,warp-2,warp-3``) for load-balance
      across multiple registered WARP accounts (sensitive mode).
    """

    enabled: bool = False
    tag: Optional[str] = Field(default="warp", max_length=512)
    mode: Optional[str] = Field(default="sensitive", max_length=16)


class NodeResponse(Node):
    id: int
    xray_version: Optional[str] = None
    status: NodeStatus
    message: Optional[str] = None
    # Pinned TLS cert fingerprint (SHA-256 hex); null until first connect.
    server_cert_sha256: Optional[str] = None
    latency_ms: Optional[float] = None
    last_health: Optional[datetime] = None
    last_ack_at: Optional[datetime] = None
    last_stats_ok: Optional[datetime] = None
    reported_peer_count: int = 0
    ssh_ok: Optional[bool] = None
    control_tunnel_ok: Optional[bool] = None
    drift: bool = False
    drift_reason: Optional[str] = None
    # UI-only: computed from DB connection status + last_ack + drift + cursor.
    # Not stored on the Postgres NodeStatus enum.
    health_status: str = "connecting"
    wireguard: Optional[NodeWireGuardConfig] = None
    singbox: Optional[NodeSingBoxConfig] = None
    # Tunnel topology role: 'direct' (default), 'relay' (in-country bridge), 'exit'.
    role: str = "direct"
    provision_status: Optional[str] = None
    provision_message: Optional[str] = None
    provision_progress: Optional[int] = None
    provision_step: Optional[str] = None
    # True when panel↔node control is going through the auto SSH tunnel.
    control_tunneled: bool = False
    model_config = ConfigDict(from_attributes=True)


class NodeGroupCreate(BaseModel):
    name: str
    region: Optional[str] = None


class NodeGroupResponse(BaseModel):
    id: int
    name: str
    region: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class NodeUsageResponse(BaseModel):
    node_id: Optional[int] = None
    node_name: str
    uplink: int
    downlink: int


class NodesUsageResponse(BaseModel):
    usages: List[NodeUsageResponse]
