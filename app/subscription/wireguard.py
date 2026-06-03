"""WireGuard client ``.conf`` generator for subscriptions (Phase 11.5).

WireGuard is not an Xray inbound, so it can't ride the v2ray/clash/sing-box
exporters in ``share.py``. Instead a user downloads a standard wg-quick config
(``[Interface]`` + one ``[Peer]`` per WireGuard node) tied to the SAME
subscription token and the SAME central ``used_traffic`` quota.

The renderer is pure (no DB / no I/O) so it is unit testable. ``user_config``
assembles the inputs from a user's WireGuard proxy settings and a WG node.
"""
from typing import List, Optional

DEFAULT_ALLOWED_IPS = "0.0.0.0/0, ::/0"
DEFAULT_KEEPALIVE = 25


def render_wireguard_conf(
    *,
    private_key: str,
    address: str,
    server_public_key: str,
    endpoint: str,
    dns: Optional[str] = None,
    preshared_key: Optional[str] = None,
    allowed_ips: str = DEFAULT_ALLOWED_IPS,
    mtu: Optional[int] = None,
    keepalive: int = DEFAULT_KEEPALIVE,
) -> str:
    """Render a single-peer wg-quick client config."""
    interface: List[str] = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {address}",
    ]
    if dns:
        interface.append(f"DNS = {dns}")
    if mtu:
        interface.append(f"MTU = {mtu}")

    peer: List[str] = [
        "[Peer]",
        f"PublicKey = {server_public_key}",
    ]
    if preshared_key:
        peer.append(f"PresharedKey = {preshared_key}")
    peer.append(f"Endpoint = {endpoint}")
    peer.append(f"AllowedIPs = {allowed_ips}")
    if keepalive:
        peer.append(f"PersistentKeepalive = {keepalive}")

    return "\n".join(interface) + "\n\n" + "\n".join(peer) + "\n"


def node_endpoint(dbnode) -> str:
    """Resolve the peer ``Endpoint`` (``host:port``) for a WG node.

    Prefers the explicitly configured ``endpoint``; otherwise derives it from
    the node address and the WireGuard listen port.
    """
    cfg = dbnode.wireguard
    if cfg.endpoint:
        return cfg.endpoint
    return f"{dbnode.address}:{cfg.listen_port}"


def user_config(user_settings: dict, dbnode) -> Optional[str]:
    """Build the ``.conf`` for one user on one WG node, or ``None`` when the
    user has no usable WireGuard credentials / address for that node."""
    cfg = dbnode.wireguard
    if cfg is None:
        return None
    private_key = user_settings.get("private_key")
    address = user_settings.get("address")
    if not private_key or not address:
        return None
    return render_wireguard_conf(
        private_key=private_key,
        address=address,
        server_public_key=cfg.public_key,
        endpoint=node_endpoint(dbnode),
        dns=cfg.dns,
        preshared_key=user_settings.get("preshared_key"),
        mtu=cfg.mtu,
    )
