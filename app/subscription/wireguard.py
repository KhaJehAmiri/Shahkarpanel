"""WireGuard client ``.conf`` generator for subscriptions (Phase 11.5).

WireGuard is not an Xray inbound, so it can't ride the v2ray/clash/sing-box
exporters in ``share.py``. Instead a user downloads a standard wg-quick config
(``[Interface]`` + one ``[Peer]`` per WireGuard node) tied to the SAME
subscription token and the SAME central ``used_traffic`` quota.

The renderer is pure (no DB / no I/O) so it is unit testable. ``user_config``
assembles the inputs from a user's WireGuard proxy settings and a WG node.
"""
from typing import Dict, List, Optional

# IPv6 is omitted until the node agent sets up v6 forwarding/NAT for WG clients.
DEFAULT_ALLOWED_IPS = "0.0.0.0/0"
DEFAULT_DNS = "1.1.1.1, 8.8.8.8"
DEFAULT_KEEPALIVE = 25

# AmneziaWG [Interface] keys, in canonical order. Values are integers.
AWG_KEYS = ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")


def amnezia_params_from_node(cfg) -> Dict[str, int]:
    """Extract AmneziaWG params when the operator enabled AWG mode on the node."""
    from app.wireguard.sync import amneziawg_enabled, awg_params_from_cfg

    if not amneziawg_enabled(cfg):
        return {}
    return awg_params_from_cfg(cfg)


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
    amnezia: Optional[Dict[str, int]] = None,
) -> str:
    """Render a single-peer wg-quick / AmneziaWG client config.

    When ``amnezia`` carries obfuscation parameters they are emitted under
    ``[Interface]`` (AmneziaWG superset of wg-quick); otherwise the output is a
    plain WireGuard config.
    """
    interface: List[str] = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {address}",
    ]
    if dns:
        interface.append(f"DNS = {dns}")
    if mtu:
        interface.append(f"MTU = {mtu}")
    if amnezia:
        for key in AWG_KEYS:
            if key in amnezia:
                interface.append(f"{key} = {amnezia[key]}")

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


def node_endpoint(dbnode, *, variant: str = "plain") -> str:
    """Resolve the peer ``Endpoint`` (``host:port``) for a WG node variant."""
    from app.wireguard.sync import amneziawg_enabled

    cfg = dbnode.wireguard
    if variant == "awg" and amneziawg_enabled(cfg):
        if cfg.awg_endpoint:
            return cfg.awg_endpoint
        return f"{dbnode.address}:{cfg.awg_listen_port}"
    if cfg.endpoint:
        return cfg.endpoint
    return f"{dbnode.address}:{cfg.listen_port}"


def user_config(user_settings: dict, dbnode, *, variant: str = "plain") -> Optional[str]:
    """Build the ``.conf`` for one user on one WG node, or ``None`` when the
    user has no usable WireGuard credentials / address for that node."""
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

    cfg = dbnode.wireguard
    if cfg is None:
        return None
    private_key = user_settings.get("private_key")
    if not private_key:
        return None
    if variant == "awg":
        if not amneziawg_enabled(cfg):
            return None
        address = user_settings.get("awg_address")
        server_public_key = cfg.awg_public_key
        amnezia = amnezia_params_from_node(cfg)
    else:
        if not plain_wg_enabled(cfg):
            return None
        address = user_settings.get("address")
        server_public_key = cfg.public_key
        amnezia = None
    if not address or not server_public_key:
        return None
    from app.wireguard.awg import AWG_RECOMMENDED_MTU

    if variant == "awg":
        mtu = AWG_RECOMMENDED_MTU
    else:
        mtu = cfg.mtu
    return render_wireguard_conf(
        private_key=private_key,
        address=address,
        server_public_key=server_public_key,
        endpoint=node_endpoint(dbnode, variant=variant),
        dns=cfg.dns or DEFAULT_DNS,
        preshared_key=user_settings.get("preshared_key"),
        mtu=mtu,
        amnezia=amnezia,
    )
