"""Xray-core's *native* userspace WireGuard inbound, Finalmask-noise obfuscated.

This is the "3x-ui style" WireGuard: unlike the kernel ``wg0`` interface
(``app/wireguard/sync.py``) or the raw dokodemo-door tunnel capture
(``app/tunnel/relay.py``), Xray-core itself speaks the WireGuard protocol in
userspace (wireguard-go + gVisor netstack) as just another inbound — no
kernel device, no ``wg`` binary. Layering Finalmask ``noise`` streamSettings
on top disguises the WireGuard handshake bytes on the wire so DPI can't
fingerprint the protocol, which is exactly what defeats Iran's handshake-drop
censorship on the client-facing hop.

Trade-off: Finalmask is an Xray-core-specific wire transform. Only
Xray-core-based clients (v2rayNG, NekoBox, Xray-knife, sing-box does *not*
implement it, etc.) can dial this — not the stock WireGuard app.

Server identity reuses this node's existing ``private_key``/``public_key``
(the same keys the kernel/plain listener already advertises), so one client
keypair keeps working no matter which transport variant is selected.
"""
from typing import Dict, List, Optional, Tuple

from app.wireguard.sync import WGUserPeer, _normalize_allowed

# A DPI-plausible default: a handful of small random-sized packets before the
# real handshake, re-armed every 30-60s per remote address. Admins can override
# via ``NodeWireGuard.xray_wg_noise`` with any Finalmask "noise" settings dict.
DEFAULT_NOISE_SETTINGS: Dict = {
    "reset": "30-60",
    "noise": [
        {"rand": "40-120", "delay": "5-20"},
    ],
}

DEFAULT_LOCAL_ADDRESS = "10.90.0.1/32"


def xray_native_wg_enabled(cfg) -> bool:
    """True when this node should expose the Xray-native WG+noise inbound."""
    if cfg is None:
        return False
    return bool(getattr(cfg, "xray_wg_enabled", False)) and bool(
        getattr(cfg, "xray_wg_listen_port", None)
    )


def xray_wg_inbound_tag(node_id: int) -> str:
    return f"node-{node_id}-xray-wg-in"


def _peer_email(peer: WGUserPeer) -> str:
    # Same convention as other protocols (app/xray/config.py) so the existing
    # per-user stats poller (record_usages.py) attributes this inbound's
    # traffic to the right user automatically.
    if peer.username:
        return f"{peer.user_id}.{peer.username}"
    return str(peer.user_id)


def build_xray_wireguard_peers(peers: List[WGUserPeer]) -> List[Dict]:
    """Peers for the Finalmask inbound.

    Tunnel IP prefers plain ``address``; falls back to ``awg_address`` so
    amnezia-only users are not dropped from the inbound.
    """
    out = []
    seen = set()
    for p in peers:
        tunnel = (p.address or p.awg_address or "").strip()
        if not p.active or not p.public_key or not tunnel or p.public_key in seen:
            continue
        seen.add(p.public_key)
        entry: Dict = {
            "publicKey": p.public_key,
            "allowedIPs": [_normalize_allowed(tunnel)],
            "email": _peer_email(p),
        }
        if p.preshared_key:
            entry["preSharedKey"] = p.preshared_key
        out.append(entry)
    return out


def build_xray_wireguard_inbound(
    cfg,
    peers: List[WGUserPeer],
    *,
    node_id: int,
    outbound_tag: str = "DIRECT",
) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Build ``(inbound, routing_rule)`` for a node's Xray-native WG+noise listener.

    Returns ``(None, None)`` when the feature is disabled or misconfigured
    (missing keys/port) so callers can skip injection safely.

    ``outbound_tag`` is DIRECT by default; pass the node's WARP tag when
    ``warp_enabled`` so Finalmask clients exit via Cloudflare.
    """
    if not xray_native_wg_enabled(cfg):
        return None, None
    if not cfg.private_key:
        return None, None

    tag = xray_wg_inbound_tag(node_id)
    noise_settings = cfg.xray_wg_noise or DEFAULT_NOISE_SETTINGS
    inbound = {
        "tag": tag,
        "listen": "0.0.0.0",
        "port": int(cfg.xray_wg_listen_port),
        "protocol": "wireguard",
        "settings": {
            "secretKey": cfg.private_key,
            "address": [DEFAULT_LOCAL_ADDRESS],
            "mtu": int(getattr(cfg, "xray_wg_mtu", None) or 1420),
            "peers": build_xray_wireguard_peers(peers),
        },
        "streamSettings": {
            "finalmask": {
                "udp": [
                    {"type": "noise", "settings": noise_settings},
                ]
            }
        },
    }
    rule = {
        "type": "field",
        "inboundTag": [tag],
        "outboundTag": outbound_tag or "DIRECT",
    }
    return inbound, rule


def build_xray_native_client_config(
    *,
    private_key: str,
    local_address: str,
    server_public_key: str,
    server_host: str,
    server_port: int,
    preshared_key: Optional[str] = None,
    mtu: int = 1420,
    noise: Optional[Dict] = None,
    local_socks_port: int = 10808,
) -> Dict:
    """Full standalone Xray-core client config: local SOCKS in -> WG+noise out.

    Import this JSON directly into an Xray-core-based client (v2rayNG,
    NekoBox, Xray-knife, ...) — Finalmask is Xray-specific, so the stock
    WireGuard app cannot use this config.
    """
    peer: Dict = {
        "publicKey": server_public_key,
        "endpoint": f"{server_host}:{server_port}",
        "allowedIPs": ["0.0.0.0/0", "::/0"],
    }
    if preshared_key:
        peer["preSharedKey"] = preshared_key

    outbound: Dict = {
        "tag": "wg-native-out",
        "protocol": "wireguard",
        "settings": {
            "secretKey": private_key,
            "address": [local_address],
            "mtu": int(mtu or 1420),
            "peers": [peer],
            # gVisor userspace stack: no real kernel interface/routes to manage
            # on the client host — matches the server side and avoids requiring
            # CAP_NET_ADMIN or touching the client's routing table at all.
            "noKernelTun": True,
        },
        "streamSettings": {
            "finalmask": {
                "udp": [
                    {"type": "noise", "settings": noise or DEFAULT_NOISE_SETTINGS},
                ]
            }
        },
    }
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": int(local_socks_port),
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
        ],
        "outbounds": [outbound, {"tag": "direct", "protocol": "freedom"}],
        "routing": {
            "rules": [
                {"type": "field", "inboundTag": ["socks-in"], "outboundTag": "wg-native-out"},
            ]
        },
    }
