"""WireGuard client ``.conf`` generator for subscriptions (Phase 11.5).

WireGuard is not an Xray inbound, so it can't ride the v2ray/clash/sing-box
exporters in ``share.py``. Instead a user downloads a standard wg-quick config
(``[Interface]`` + one ``[Peer]`` per WireGuard node) tied to the SAME
subscription token and the SAME central ``used_traffic`` quota.

The renderer is pure (no DB / no I/O) so it is unit testable. ``user_config``
assembles the inputs from a user's WireGuard proxy settings and a WG node.
"""
from typing import Dict, List, Optional, Union

# IPv6 is omitted until the node agent sets up v6 forwarding/NAT for WG clients.
DEFAULT_ALLOWED_IPS = "0.0.0.0/0"
DEFAULT_DNS = "1.1.1.1, 8.8.8.8"
DEFAULT_KEEPALIVE = 10

# Hosts that clients on the public Internet can never dial.
_NON_ROUTABLE_HOSTS = frozenset({
    "", "0.0.0.0", "::", "::1", "127.0.0.1", "localhost",
})

# AmneziaWG [Interface] keys, in canonical order. I* are client-only hex strings.
AWG_KEYS = (
    "Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4",
    "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5",
)
AwgValue = Union[int, str]


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
    amnezia: Optional[Dict[str, AwgValue]] = None,
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


def _join_host_port(host: str, port: int) -> str:
    import ipaddress

    host = host.strip("[]")
    try:
        if isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address):
            return f"[{host}]:{port}"
    except ValueError:
        pass
    return f"{host}:{port}"


def _encode_userinfo(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="").replace("+", "%20")


def wireguard_share_link(
    *,
    private_key: str,
    server: str,
    port: int,
    server_public_key: str,
    local_address: str,
    mtu: Optional[int] = None,
    preshared_key: Optional[str] = None,
    keepalive: Optional[int] = None,
    dns: Optional[str] = None,
    remark: str = "",
) -> str:
    """Build a v2rayNG / 3x-ui compatible ``wireguard://`` subscription link.

    Format mirrors 3x-ui ``genWireguardLink``:
    ``wireguard://<privateKey>@host:port?publickey=...&address=<client-ip>&mtu=...#remark``
    """
    from urllib.parse import quote, urlencode

    authority = _join_host_port(server, port)
    link = f"wireguard://{_encode_userinfo(private_key)}@{authority}"

    params: dict[str, str] = {
        "publickey": server_public_key,
        "address": local_address,
    }
    if mtu:
        params["mtu"] = str(mtu)
    if preshared_key:
        params["presharedkey"] = preshared_key
    if keepalive:
        params["keepalive"] = str(keepalive)
    if dns:
        params["dns"] = dns

    uri = f"{link}?{urlencode(params, quote_via=lambda s, *_a, **_kw: quote(s, safe=''))}"
    if remark:
        uri += f"#{quote(remark, safe='')}"
    return uri


def _parse_wireguard_conf(conf: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {"interface": {}, "peer": {}}
    current: Optional[str] = None
    for line in conf.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower == "[interface]":
            current = "interface"
            continue
        if lower == "[peer]":
            current = "peer"
            continue
        if current and "=" in line:
            key, value = [part.strip() for part in line.split("=", 1)]
            sections[current][key.lower()] = value
    return sections


def wireguard_import_uri(conf: str, remark: str = "") -> str:
    """Build a ``wireguard://`` share link from a wg-quick config body."""
    parsed = _parse_wireguard_conf(conf)
    iface = parsed["interface"]
    peer = parsed["peer"]
    endpoint = peer.get("endpoint", "")
    if ":" in endpoint:
        host, port_str = endpoint.rsplit(":", 1)
        port = int(port_str)
    else:
        host, port = endpoint, 51820
    keepalive_raw = peer.get("persistentkeepalive")
    return wireguard_share_link(
        private_key=iface.get("privatekey", ""),
        server=host,
        port=port,
        server_public_key=peer.get("publickey", ""),
        local_address=iface.get("address", ""),
        mtu=int(iface["mtu"]) if iface.get("mtu") else None,
        preshared_key=peer.get("presharedkey"),
        keepalive=int(keepalive_raw) if keepalive_raw else DEFAULT_KEEPALIVE,
        dns=iface.get("dns"),
        remark=remark,
    )


def _awg_requires_conf_download(cfg) -> bool:
    """AWG obfuscation keys cannot be encoded in ``wireguard://`` URIs."""
    from app.wireguard.sync import amneziawg_enabled, sg_wire_enabled

    if not amneziawg_enabled(cfg):
        return False
    if sg_wire_enabled(cfg):
        return True
    return bool(amnezia_params_from_node(cfg))


def _server_public_key(dbnode, *, variant: str = "plain", db=None) -> Optional[str]:
    """Resolve the server pubkey clients must trust for this node variant."""
    from app.db import GetDB
    from app.tunnel.relay import node_delegates_wireguard_to_tunnel, relay_wireguard_server_public_key
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

    cfg = dbnode.wireguard
    if cfg is None:
        return None
    if variant == "awg":
        if not amneziawg_enabled(cfg):
            return None
        return str(getattr(cfg, "awg_public_key", "") or "") or None

    if variant == "direct":
        # Direct listener is the node's own identity, never the tunnel's
        # delegated/panel-exit key — traffic terminates locally here.
        from app.wireguard.sync import direct_wg_enabled

        if not direct_wg_enabled(cfg):
            return None
        return str(getattr(cfg, "public_key", "") or "") or None

    if not plain_wg_enabled(cfg):
        return None

    session = db
    live_node = None
    try:
        from app import xray

        live_node = xray.nodes.get(int(dbnode.id))
    except Exception:
        live_node = None
    if session is None:
        with GetDB() as session:
            if node_delegates_wireguard_to_tunnel(session, dbnode.id):
                delegated = relay_wireguard_server_public_key(
                    session, dbnode.id, node_object=live_node
                )
                if delegated:
                    return delegated
    elif node_delegates_wireguard_to_tunnel(session, dbnode.id):
        delegated = relay_wireguard_server_public_key(
            session, dbnode.id, node_object=live_node
        )
        if delegated:
            return delegated

    return str(getattr(cfg, "public_key", "") or "") or None


def user_share_link(
    user_settings: dict,
    dbnode,
    *,
    variant: str = "plain",
    remark: str = "",
    db=None,
) -> Optional[str]:
    """Build a subscription share link for one user on one WG node."""
    cfg = dbnode.wireguard
    if variant == "awg" and _awg_requires_conf_download(cfg):
        # Amnezia / AWG clients must import ``/sub/{token}/wireguard?variant=awg``.
        return None
    if user_config(user_settings, dbnode, variant=variant, db=db) is None:
        return None

    cfg = dbnode.wireguard
    host, port_str = node_endpoint(dbnode, variant=variant, db=db).rsplit(":", 1)
    if variant == "awg":
        local_address = user_settings.get("awg_address") or ""
        server_public_key = _server_public_key(dbnode, variant=variant, db=db)
        from app.wireguard.awg import AWG_RECOMMENDED_MTU

        mtu = AWG_RECOMMENDED_MTU
    else:
        local_address = user_settings.get("address") or ""
        server_public_key = _server_public_key(dbnode, variant=variant, db=db)
        mtu = cfg.mtu

    return wireguard_share_link(
        private_key=user_settings["private_key"],
        server=host,
        port=int(port_str),
        server_public_key=server_public_key,
        local_address=local_address,
        mtu=mtu,
        preshared_key=user_settings.get("preshared_key"),
        keepalive=DEFAULT_KEEPALIVE,
        dns=getattr(cfg, "dns", None),
        remark=remark,
    )


def _endpoint_host(raw: Optional[str]) -> str:
    """Extract host from ``host``, ``host:port``, or ``[v6]:port``."""
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("["):
        end = text.find("]")
        if end > 1:
            return text[1:end].strip()
    if text.count(":") == 1:
        return text.rsplit(":", 1)[0].strip()
    return text


def _is_non_routable_host(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    if not h or h in _NON_ROUTABLE_HOSTS:
        return True
    if h.startswith("127."):
        return True
    return False


def public_dial_host(dbnode) -> str:
    """Public host clients should dial for this WG node.

    Control-plane ``nodes.address`` may be loopback (SSH tunnel / RPyC). Prefer
    an explicit routable endpoint host, then ``provision_host``, then address.
    """
    cfg = getattr(dbnode, "wireguard", None)
    candidates = [
        _endpoint_host(getattr(cfg, "endpoint", None) if cfg else None),
        _endpoint_host(getattr(cfg, "awg_endpoint", None) if cfg else None),
        (getattr(dbnode, "provision_host", None) or "").strip(),
        (getattr(dbnode, "address", None) or "").strip(),
    ]
    for host in candidates:
        if host and not _is_non_routable_host(host):
            return host
    for host in candidates:
        if host:
            return host
    return ""


def node_endpoint(dbnode, *, variant: str = "plain", db=None) -> str:
    """Resolve the peer ``Endpoint`` (``host:port``) for a WG node variant.

    Never advertise control-plane loopback to clients. When the relay delegates
    plain WG through an Xray dokodemo tunnel, use that tunnel's capture port.
    """
    from app.wireguard.sync import amneziawg_enabled, direct_wg_enabled

    cfg = dbnode.wireguard
    host = public_dial_host(dbnode)

    if variant == "awg" and amneziawg_enabled(cfg):
        port = int(cfg.awg_listen_port or 0)
        awg_host = _endpoint_host(cfg.awg_endpoint)
        if awg_host and not _is_non_routable_host(awg_host):
            host = awg_host
            if cfg.awg_endpoint and ":" in str(cfg.awg_endpoint):
                try:
                    port = int(str(cfg.awg_endpoint).rsplit(":", 1)[-1])
                except ValueError:
                    pass
        return f"{host}:{port}"

    if variant == "direct" and direct_wg_enabled(cfg):
        return f"{host}:{int(cfg.direct_listen_port)}"

    port = int(cfg.listen_port or 0)
    # Prefer an explicit routable endpoint's port when present.
    ep_host = _endpoint_host(cfg.endpoint)
    if cfg.endpoint and ep_host and not _is_non_routable_host(ep_host):
        host = ep_host
        try:
            port = int(str(cfg.endpoint).rsplit(":", 1)[-1])
        except ValueError:
            pass

    # Tunnel-delegated plain WG: clients must hit dokodemo capture port on relay.
    try:
        from app.tunnel.relay import relay_wireguard_tunnel_port

        if db is not None:
            tun_port = relay_wireguard_tunnel_port(db, int(dbnode.id))
            if tun_port:
                port = int(tun_port)
        else:
            from app.db import GetDB

            with GetDB() as session:
                tun_port = relay_wireguard_tunnel_port(session, int(dbnode.id))
                if tun_port:
                    port = int(tun_port)
    except Exception:
        pass

    return f"{host}:{port}"


def user_config(user_settings: dict, dbnode, *, variant: str = "plain", db=None) -> Optional[str]:
    """Build the ``.conf`` for one user on one WG node, or ``None`` when the
    user has no usable WireGuard credentials / address for that node."""
    from app.wireguard.sync import (amneziawg_enabled, direct_wg_enabled,
                                     plain_wg_enabled, sg_wire_enabled)

    cfg = dbnode.wireguard
    if cfg is None:
        return None
    private_key = user_settings.get("private_key")
    if not private_key:
        return None
    if variant == "direct":
        if not direct_wg_enabled(cfg):
            return None
        address = user_settings.get("address")
        server_public_key = _server_public_key(dbnode, variant=variant, db=db)
        amnezia = None
    elif variant == "awg":
        if not amneziawg_enabled(cfg):
            return None
        if sg_wire_enabled(cfg):
            from app.sigmaguard_wire.bridge import build_client_conf

            return build_client_conf(
                user_settings,
                dbnode,
                dns=cfg.dns or DEFAULT_DNS,
            )
        address = user_settings.get("awg_address")
        server_public_key = _server_public_key(dbnode, variant=variant, db=db)
        amnezia = amnezia_params_from_node(cfg)
    else:
        if not plain_wg_enabled(cfg):
            return None
        address = user_settings.get("address")
        server_public_key = _server_public_key(dbnode, variant=variant, db=db)
        amnezia = None
    if not address or not server_public_key:
        return None
    from app.wireguard.awg import AWG_RECOMMENDED_MTU

    if variant == "awg":
        mtu = AWG_RECOMMENDED_MTU
        dns = cfg.dns or DEFAULT_DNS
    else:
        mtu = cfg.mtu
        # Omit DNS on plain wg-quick exports: resolvconf failures tear the iface down
        # on hosts without systemd-resolved (common on minimal Linux/VPS images).
        dns = None
    return render_wireguard_conf(
        private_key=private_key,
        address=address,
        server_public_key=server_public_key,
        endpoint=node_endpoint(dbnode, variant=variant, db=db),
        dns=dns,
        preshared_key=user_settings.get("preshared_key"),
        mtu=mtu,
        amnezia=amnezia,
    )
