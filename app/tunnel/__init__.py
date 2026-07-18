"""In-country relay -> foreign exit tunnels (phase 6).

Many protocols don't survive a *direct* connection from inside Iran to a foreign
server, so a common topology is:

    client --> relay (in Iran) --> exit (abroad) --> internet

The client connects to the relay with a normal proxy inbound. The relay then
forwards that traffic to the *exit* over an encrypted hop (VLESS over
Reality/WS/gRPC/TCP). The exit decrypts and dials the internet from its own
(foreign) IP.

Either end may be a registered node or the panel's own local Xray core (when
the tunnel's ``relay_node_id`` / ``exit_node_id`` is ``NULL``).

This module turns a :class:`~app.db.models.Tunnel` row into the Xray config
fragments that implement the hop:

* ``build_relay_outbound`` — the outbound the relay uses to reach the exit.
* ``build_relay_routing_rule`` — pins the relay's user/WireGuard inbound traffic
  to that outbound tag.
* ``build_exit_inbound`` — the inbound the exit listens on; its traffic exits
  via ``freedom`` (straight to the internet).
* ``build_wireguard_relay_inbound`` — a ``dokodemo-door`` UDP capture on the
  relay so the panel's native WireGuard service is carried *inside* the Reality
  tunnel to the exit (WireGuard-over-Reality), rather than exposed directly.

Everything here is pure and deterministic given the tunnel + its params (key
generation is the one impure helper and is isolated), so it is trivially
testable and can be assembled into a node's running config by the xray layer.
"""
import secrets
import subprocess
import uuid
from typing import Dict, List, Literal, Optional, Tuple

__all__ = [
    "SUPPORTED_TRANSPORTS",
    "TUNNEL_TRANSPORT_META",
    "default_params",
    "generate_reality_keys",
    "ensure_reality_keys",
    "ensure_quic_key",
    "ensure_singbox_tunnel_secrets",
    "build_relay_outbound",
    "build_relay_routing_rule",
    "build_intermediate_inbound",
    "build_intermediate_outbound",
    "build_intermediate_routing_rule",
    "build_exit_inbound",
    "build_wireguard_relay_inbound",
    "singbox_socks_port",
    "build_singbox_bridge_socks_inbound",
    "build_singbox_bridge_routing_rule",
    "build_tunnel_pair",
    "build_singbox_tunnel_fragments",
    "tunnel_hops",
    "transit_port",
    "transport_engine",
    "validate_transport",
]

TunnelEngine = Literal["xray", "singbox"]

TUNNEL_TRANSPORT_META: dict[str, dict] = {
    "reality": {"label": "VLESS + Reality", "engine": "xray", "description": "VLESS Reality (no Vision flow — tunnel/UDP safe)"},
    "ws": {"label": "VLESS + WebSocket", "engine": "xray", "description": "WebSocket + TLS hop"},
    "grpc": {"label": "VLESS + gRPC", "engine": "xray", "description": "gRPC transport hop"},
    "tcp": {"label": "VLESS + TCP", "engine": "xray", "description": "Plain TCP hop"},
    "quic": {"label": "VLESS + QUIC/TLS", "engine": "xray", "description": "VLESS over QUIC (HTTP/3 ALPN)"},
    "hysteria2": {
        "label": "Hysteria2 (sing-box)",
        "engine": "singbox",
        "stub": True,
        "description": "QUIC obfs hop — sing-box fragments; manual merge on exit",
    },
    "tuic": {
        "label": "TUIC (sing-box)",
        "engine": "singbox",
        "stub": True,
        "description": "QUIC TUIC hop — sing-box fragments; manual merge on exit",
    },
}

SUPPORTED_TRANSPORTS = tuple(TUNNEL_TRANSPORT_META.keys())


def clean_public_host(raw: str) -> str:
    """Extract a bare host/IP from a ``PANEL_PUBLIC_ADDRESS``-style value.

    Accepts full URLs (``https://host[:port]/path``), ``host:port`` and bare
    hosts, returning just the host. A naive ``split(":")[0]`` breaks on a URL
    scheme (``https://ip`` -> ``"https"``), which would make a relay dial the
    literal address ``"https"`` and silently kill the tunnel.
    """
    host = (raw or "").strip()
    if not host:
        return ""
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0]          # drop any path
    if "@" in host:
        host = host.rsplit("@", 1)[1]     # drop userinfo
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")]    # IPv6 literal [::1]:port
    if host.count(":") == 1:
        host = host.split(":", 1)[0]      # drop host:port
    return host.strip()


def transport_engine(transport: str) -> TunnelEngine:
    validate_transport(transport)
    return TUNNEL_TRANSPORT_META[transport]["engine"]  # type: ignore[return-value]


def validate_transport(transport: str) -> str:
    if transport not in SUPPORTED_TRANSPORTS:
        raise ValueError(f"unsupported transport: {transport!r} (use one of {SUPPORTED_TRANSPORTS})")
    return transport


def generate_reality_keys() -> Dict[str, str]:
    """Generate a Reality x25519 keypair via ``xray x25519``.

    Returns ``{"private_key": ..., "public_key": ...}``. Raises ``RuntimeError``
    if the xray binary is missing or its output can't be parsed, so callers can
    decide whether to fail the request or fall back.
    """
    from config import XRAY_EXECUTABLE_PATH

    try:
        proc = subprocess.run(
            [XRAY_EXECUTABLE_PATH, "x25519"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"failed to run `{XRAY_EXECUTABLE_PATH} x25519`: {exc}") from exc

    private_key = public_key = ""
    for line in proc.stdout.splitlines():
        low = line.lower()
        # xray prints e.g. "Private key: <...>" / "Public key: <...>".
        if "private" in low and ":" in line:
            private_key = line.split(":", 1)[1].strip()
        elif "public" in low and ":" in line:
            public_key = line.split(":", 1)[1].strip()
    if not private_key or not public_key:
        raise RuntimeError(f"could not parse keys from xray x25519 output: {proc.stdout!r}")
    return {"private_key": private_key, "public_key": public_key}


def ensure_reality_keys(params: Dict) -> Dict:
    """Fill empty Reality ``private_key``/``public_key`` in ``params`` in place.

    No-op for non-reality params or when both keys are already present. Silently
    leaves keys empty if generation is unavailable (e.g. no xray binary in a
    test/dev box) — config assembly still produces valid structure.
    """
    if params.get("private_key") and params.get("public_key"):
        return params
    try:
        keys = generate_reality_keys()
    except RuntimeError:
        return params
    params.setdefault("private_key", "")
    params.setdefault("public_key", "")
    if not params["private_key"]:
        params["private_key"] = keys["private_key"]
    if not params["public_key"]:
        params["public_key"] = keys["public_key"]
    return params


def ensure_quic_key(params: Dict) -> Dict:
    """Fill an empty QUIC ``key`` in ``params`` (Xray quicSettings.key)."""
    if not params.get("key"):
        params["key"] = secrets.token_hex(8)
    return params


def ensure_singbox_tunnel_secrets(params: Dict, transport: str) -> Dict:
    """Seed passwords/uuids for sing-box tunnel stubs."""
    if transport == "hysteria2":
        if not params.get("password"):
            params["password"] = str(uuid.uuid4())
        if not params.get("obfs_password"):
            params["obfs_password"] = secrets.token_hex(8)
        params.setdefault("sni", "www.cloudflare.com")
        params.setdefault("up_mbps", 100)
        params.setdefault("down_mbps", 200)
    elif transport == "tuic":
        if not params.get("uuid"):
            params["uuid"] = str(uuid.uuid4())
        if not params.get("password"):
            params["password"] = str(uuid.uuid4())
        params.setdefault("congestion_control", "bbr")
        params.setdefault("sni", "www.cloudflare.com")
        params.setdefault("alpn", "h3")
    return params


def default_params(transport: str) -> Dict:
    """Sensible default transport params (also used to seed a new tunnel)."""
    validate_transport(transport)
    client_id = str(uuid.uuid4())
    if transport == "reality":
        # No ``flow``: xtls-rprx-vision breaks dokodemo/UDP (WireGuard-over-tunnel).
        return {
            "id": client_id,
            "sni": "www.cloudflare.com",
            "fingerprint": "chrome",
            # Filled by ``ensure_reality_keys`` (xray x25519) at creation time;
            # empty placeholders keep the structure valid for assembly/tests.
            "public_key": "",
            "private_key": "",
            "short_id": uuid.uuid4().hex[:8],
        }
    if transport == "ws":
        return {"id": client_id, "path": "/tunnel", "host": ""}
    if transport == "grpc":
        return {"id": client_id, "service_name": "tunnel"}
    if transport == "quic":
        return {
            "id": client_id,
            "security": "tls",
            "sni": "www.cloudflare.com",
            "alpn": "h3",
            "key": "",
            "header_type": "none",
        }
    if transport == "hysteria2":
        return {
            "password": "",
            "obfs_password": "",
            "sni": "www.cloudflare.com",
            "up_mbps": 100,
            "down_mbps": 200,
        }
    if transport == "tuic":
        return {
            "uuid": "",
            "password": "",
            "congestion_control": "bbr",
            "sni": "www.cloudflare.com",
            "alpn": "h3",
        }
    return {"id": client_id}  # tcp


def _stream_settings(transport: str, params: Dict, *, server_side: bool) -> Dict:
    network = "tcp" if transport in ("reality", "tcp") else transport
    stream: Dict = {"network": network}

    if transport == "reality":
        stream["security"] = "reality"
        sni = params.get("sni", "www.cloudflare.com")
        short_id = params.get("short_id", "")
        fingerprint = params.get("fingerprint", "chrome")
        if server_side:
            # Match product Reality inbounds: fingerprint/publicKey live under
            # nested ``settings`` (uTLS when dialing dest). Top-level fingerprint
            # is a client field and was leaving node→node exits misconfigured.
            reality = {
                "show": False,
                "serverNames": [sni],
                "shortIds": [short_id],
                "privateKey": params.get("private_key", ""),
                "target": f"{sni}:443",
                "settings": {
                    "publicKey": params.get("public_key", ""),
                    "fingerprint": fingerprint,
                },
            }
        else:
            reality = {
                "show": False,
                "fingerprint": fingerprint,
                "publicKey": params.get("public_key", ""),
                "serverName": sni,
                "shortId": short_id,
            }
        stream["realitySettings"] = reality
    elif transport == "ws":
        stream["wsSettings"] = {
            "path": params.get("path", "/tunnel"),
            "headers": ({"Host": params["host"]} if params.get("host") else {}),
        }
    elif transport == "grpc":
        stream["grpcSettings"] = {"serviceName": params.get("service_name", "tunnel")}
    elif transport == "quic":
        stream["security"] = params.get("security", "tls")
        key = str(params.get("key") or "").strip()
        path = key if key.startswith("/") else (f"/{key}" if key else "/tunnel")
        stream["network"] = "xhttp"
        stream["xhttpSettings"] = {"path": path, "mode": "stream-one"}
        if stream["security"] == "tls":
            alpn_raw = params.get("alpn", "h3")
            if isinstance(alpn_raw, str):
                alpn = [x.strip() for x in alpn_raw.split(",") if x.strip()]
            elif isinstance(alpn_raw, list):
                alpn = [str(x).strip() for x in alpn_raw if str(x).strip()]
            else:
                alpn = ["h3"]
            if "h3" not in alpn:
                alpn = ["h3"] + [a for a in alpn if a != "h3"]
            tls: Dict = {
                "serverName": params.get("sni", "www.cloudflare.com"),
                "alpn": alpn,
            }
            if server_side:
                # A TLS *inbound* must carry a certificate or Xray refuses to
                # start it ("empty certificate"), taking the exit core down.
                # Reuse the node's provisioned TLS cert (self-signed by default);
                # callers may override the paths via params.
                from app.tls.acme import DEFAULT_CERT, DEFAULT_KEY

                tls["certificates"] = [
                    {
                        "certificateFile": params.get("cert_file") or DEFAULT_CERT,
                        "keyFile": params.get("key_file") or DEFAULT_KEY,
                        "ocspStapling": 3600,
                    }
                ]
            else:
                # The exit cert is typically self-signed / SNI-mismatched, so the
                # relay client must not abort the handshake over trust.
                tls["allowInsecure"] = True
            stream["tlsSettings"] = tls

    return stream


def outbound_tag(tunnel) -> str:
    return f"tunnel-{tunnel.id}-out"


def intermediate_inbound_tag(tunnel) -> str:
    return f"tunnel-{tunnel.id}-transit-in"


def intermediate_outbound_tag(tunnel) -> str:
    return f"tunnel-{tunnel.id}-transit-out"


def tunnel_hops(tunnel) -> int:
    """2 = relay→exit, 3 = relay→transit→exit."""
    return 3 if getattr(tunnel, "intermediate_node_id", None) else 2


def transit_port(tunnel) -> int:
    """Port the transit node listens on for the first encrypted hop."""
    explicit = getattr(tunnel, "intermediate_port", None)
    if explicit:
        return int(explicit)
    target = int(tunnel.target_port)
    return target - 1 if target > 1024 else target + 1


def build_hop_outbound(tunnel, address: str, port: int, *, tag: str) -> Dict:
    transport = validate_transport(tunnel.transport)
    if transport_engine(transport) != "xray":
        raise ValueError(f"build_hop_outbound requires an xray transport, got {transport!r}")
    params = tunnel.params or default_params(transport)

    return {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": address,
                    "port": int(port),
                    "users": [
                        {
                            "id": params.get("id"),
                            "encryption": "none",
                            **({"flow": params["flow"]} if params.get("flow") else {}),
                        }
                    ],
                }
            ]
        },
        "streamSettings": _stream_settings(transport, params, server_side=False),
    }


def build_relay_outbound(tunnel, next_address: str, *, next_port: Optional[int] = None) -> Dict:
    """Return the VLESS outbound the relay uses to dial the next hop."""
    port = int(next_port if next_port is not None else tunnel.target_port)
    return build_hop_outbound(tunnel, next_address, port, tag=outbound_tag(tunnel))


def build_relay_routing_rule(tunnel, inbound_tags: Optional[List[str]] = None) -> Dict:
    """Pin relay inbound traffic to the tunnel outbound.

    ``inbound_tags`` is the list of the relay's user (and WireGuard capture)
    inbound tags whose traffic should traverse the tunnel. When omitted, a
    catch-all rule routes *all* relay ingress through the tunnel — appropriate
    for a dedicated relay box.
    """
    rule: Dict = {"type": "field", "outboundTag": outbound_tag(tunnel)}
    if inbound_tags:
        rule["inboundTag"] = list(inbound_tags)
    else:
        rule["network"] = "tcp,udp"
    return rule


def build_exit_inbound(tunnel) -> Dict:
    """Return the inbound the exit node listens on for this tunnel."""
    transport = validate_transport(tunnel.transport)
    if transport_engine(transport) != "xray":
        raise ValueError(f"build_exit_inbound requires an xray transport, got {transport!r}")
    params = tunnel.params or default_params(transport)

    return {
        "tag": f"tunnel-{tunnel.id}-exit",
        "listen": "0.0.0.0",
        "port": int(tunnel.target_port),
        "protocol": "vless",
        "settings": {
            "clients": [
                {
                    "id": params.get("id"),
                    **({"flow": params["flow"]} if params.get("flow") else {}),
                }
            ],
            "decryption": "none",
        },
        "streamSettings": _stream_settings(transport, params, server_side=True),
    }


def build_intermediate_inbound(tunnel) -> Dict:
    """Inbound on the transit node — receives traffic from the relay hop."""
    transport = validate_transport(tunnel.transport)
    if transport_engine(transport) != "xray":
        raise ValueError(f"build_intermediate_inbound requires an xray transport, got {transport!r}")
    params = tunnel.params or default_params(transport)

    return {
        "tag": intermediate_inbound_tag(tunnel),
        "listen": "0.0.0.0",
        "port": transit_port(tunnel),
        "protocol": "vless",
        "settings": {
            "clients": [
                {
                    "id": params.get("id"),
                    **({"flow": params["flow"]} if params.get("flow") else {}),
                }
            ],
            "decryption": "none",
        },
        "streamSettings": _stream_settings(transport, params, server_side=True),
    }


def build_intermediate_outbound(tunnel, exit_address: str) -> Dict:
    """Outbound on the transit node — second hop to the exit."""
    return build_hop_outbound(
        tunnel,
        exit_address,
        int(tunnel.target_port),
        tag=intermediate_outbound_tag(tunnel),
    )


def build_intermediate_routing_rule(tunnel) -> Dict:
    """Pin transit inbound traffic to the exit-bound outbound."""
    return {
        "type": "field",
        "inboundTag": [intermediate_inbound_tag(tunnel)],
        "outboundTag": intermediate_outbound_tag(tunnel),
    }


def singbox_socks_port(tunnel) -> int:
    """Loopback port where Xray exposes a SOCKS inbound for sing-box relay egress."""
    return 18000 + int(tunnel.id)


def build_singbox_bridge_socks_inbound(tunnel) -> Dict:
    """Local SOCKS inbound on the relay Xray core for sing-box tunnel egress."""
    return {
        "tag": f"tunnel-{tunnel.id}-sb-socks",
        "listen": "127.0.0.1",
        "port": singbox_socks_port(tunnel),
        "protocol": "socks",
        "settings": {"auth": "noauth", "udp": True},
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
        },
    }


def build_singbox_bridge_routing_rule(tunnel) -> Dict:
    """Route sing-box's SOCKS bridge through the tunnel outbound."""
    return {
        "type": "field",
        "inboundTag": [f"tunnel-{tunnel.id}-sb-socks"],
        "outboundTag": outbound_tag(tunnel),
    }


def build_wireguard_relay_inbound(
    tunnel,
    wg_listen_port: int,
    *,
    wg_target_address: str = "127.0.0.1",
    wg_target_port: Optional[int] = None,
) -> Tuple[Dict, Dict]:
    """Capture the panel's WireGuard UDP on the relay and tunnel it to the exit.

    The panel's WireGuard service is a *native* interface that runs on the exit
    end. To carry it inside Reality (rather than exposing WireGuard directly to
    Iran), the relay opens a ``dokodemo-door`` UDP inbound on the WireGuard port
    and forwards every packet, via the tunnel outbound, to the exit's WireGuard
    server (``wg_target_address``:``wg_target_port`` — typically the exit's
    loopback, dialed by the exit's ``freedom`` outbound after decryption).

    ``wg_listen_port`` is the UDP port clients dial on the relay; ``wg_target_port``
    is where the exit-side native WireGuard listens (often 51820 on the panel even
    when the relay must expose a different public port).

    Returns ``(inbound, routing_rule)``.
    """
    target_port = int(wg_target_port if wg_target_port is not None else wg_listen_port)
    tag = f"tunnel-{tunnel.id}-wg-in"
    # No streamSettings: ``network: tcp`` there made some Xray builds treat the
    # listener as TCP-only and drop WireGuard UDP before it reached the tunnel.
    inbound = {
        "tag": tag,
        "listen": "0.0.0.0",
        "port": int(wg_listen_port),
        "protocol": "dokodemo-door",
        "settings": {
            "address": wg_target_address,
            "port": target_port,
            "network": "udp",
            "followRedirect": False,
        },
    }
    routing_rule = build_relay_routing_rule(tunnel, [tag])
    return inbound, routing_rule


def build_singbox_tunnel_fragments(tunnel, exit_address: str) -> Dict:
    """Sing-box hop fragments for hysteria2/tuic tunnel transports (stub).

    Relay-side Xray still routes user traffic; these JSON fragments are meant
    for a sing-box listener/outbound on the exit (and optional sidecar). They
    are returned by ``GET /tunnels/{id}/config`` but are not auto-injected into
    the Xray core yet.
    """
    transport = validate_transport(tunnel.transport)
    if transport_engine(transport) != "singbox":
        raise ValueError(f"not a sing-box tunnel transport: {transport!r}")
    params = tunnel.params or default_params(transport)
    ensure_singbox_tunnel_secrets(params, transport)
    tag = outbound_tag(tunnel)
    tls = {
        "enabled": True,
        "server_name": params.get("sni", "www.cloudflare.com"),
        "insecure": True,
    }

    if transport == "hysteria2":
        outbound = {
            "type": "hysteria2",
            "tag": tag,
            "server": exit_address,
            "server_port": int(tunnel.target_port),
            "password": params["password"],
            "tls": dict(tls),
        }
        if params.get("obfs_password"):
            outbound["obfs"] = {"type": "salamander", "password": params["obfs_password"]}
        inbound = {
            "type": "hysteria2",
            "tag": f"tunnel-{tunnel.id}-exit",
            "listen": "0.0.0.0",
            "listen_port": int(tunnel.target_port),
            "users": [{"password": params["password"]}],
            "tls": dict(tls),
        }
        if params.get("obfs_password"):
            inbound["obfs"] = {"type": "salamander", "password": params["obfs_password"]}
        if params.get("up_mbps"):
            inbound["up_mbps"] = int(params["up_mbps"])
        if params.get("down_mbps"):
            inbound["down_mbps"] = int(params["down_mbps"])
    else:  # tuic
        outbound = {
            "type": "tuic",
            "tag": tag,
            "server": exit_address,
            "server_port": int(tunnel.target_port),
            "uuid": params["uuid"],
            "password": params["password"],
            "congestion_control": params.get("congestion_control", "bbr"),
            "tls": dict(tls),
        }
        inbound = {
            "type": "tuic",
            "tag": f"tunnel-{tunnel.id}-exit",
            "listen": "0.0.0.0",
            "listen_port": int(tunnel.target_port),
            "users": [{"uuid": params["uuid"], "password": params["password"]}],
            "congestion_control": params.get("congestion_control", "bbr"),
            "tls": dict(tls),
        }

    return {
        "engine": "singbox",
        "stub": True,
        "transport": transport,
        "relay": {"outbound": outbound, "routing_rule": build_relay_routing_rule(tunnel)},
        "exit": {"inbound": inbound},
    }


def build_tunnel_pair(
    tunnel,
    exit_address: str,
    *,
    intermediate_address: Optional[str] = None,
    relay_inbound_tags: Optional[List[str]] = None,
    wireguard_port: Optional[int] = None,
) -> Dict:
    """Full config fragments for every endpoint in the tunnel chain.

    ``exit_address`` is the address the last hop dials (or the relay dials in a
    2-end tunnel). For 3-hop chains pass ``intermediate_address`` too.

    Sing-box transports (``hysteria2``, ``tuic``) return stub fragments only.
    """
    transport = validate_transport(tunnel.transport)
    if transport_engine(transport) == "singbox":
        fragments = build_singbox_tunnel_fragments(tunnel, exit_address)
        fragments["tunnel_id"] = tunnel.id
        fragments["hops"] = tunnel_hops(tunnel)
        return fragments

    hops = tunnel_hops(tunnel)
    if hops >= 3 and not intermediate_address:
        raise ValueError("intermediate_address is required for a 3-hop tunnel")

    if hops >= 3:
        relay_out = build_relay_outbound(tunnel, intermediate_address, next_port=transit_port(tunnel))
    else:
        relay_out = build_relay_outbound(tunnel, exit_address)

    routing_rules = [build_relay_routing_rule(tunnel, relay_inbound_tags)]

    relay: Dict = {
        "outbound": relay_out,
        "routing_rule": routing_rules[0],
        "routing_rules": routing_rules,
        "client_listen_port": int(tunnel.listen_port),
    }

    if wireguard_port is not None:
        wg_inbound, wg_rule = build_wireguard_relay_inbound(
            tunnel,
            wireguard_port,
            wg_target_port=(tunnel.params or {}).get("wireguard_target_port"),
        )
        relay["wireguard_inbound"] = wg_inbound
        routing_rules.append(wg_rule)

    result: Dict = {
        "tunnel_id": tunnel.id,
        "transport": tunnel.transport,
        "hops": hops,
        "relay": relay,
        "exit": {
            "inbound": build_exit_inbound(tunnel),
        },
    }

    if hops >= 3:
        result["intermediate"] = {
            "inbound": build_intermediate_inbound(tunnel),
            "outbound": build_intermediate_outbound(tunnel, exit_address),
            "routing_rule": build_intermediate_routing_rule(tunnel),
            "listen_port": transit_port(tunnel),
        }

    return result
