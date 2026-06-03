"""In-country relay -> foreign exit tunnels (phase 6).

Many protocols don't survive a *direct* connection from inside Iran to a foreign
server, so a common topology is:

    client --> relay node (in Iran) --> exit node (abroad) --> internet

The client connects to the relay with a normal proxy inbound. The relay then
forwards that traffic to the *exit* over an encrypted hop (VLESS over
Reality/WS/gRPC/TCP). The exit decrypts and dials the internet from its own
(foreign) IP.

This module turns a :class:`~app.db.models.Tunnel` row into the two Xray config
fragments that implement the hop:

* ``build_relay_outbound`` — the outbound the relay uses to reach the exit, plus
  a routing rule that pins client traffic to it.
* ``build_exit_inbound`` — the inbound the exit listens on, whose outbound is
  ``freedom`` (straight to the internet).

Everything here is pure and deterministic given the tunnel + its params, so it
is trivially testable and can be assembled into a node's running config by the
xray layer.
"""
import uuid
from typing import Dict, List, Optional, Tuple

__all__ = [
    "SUPPORTED_TRANSPORTS",
    "default_params",
    "build_relay_outbound",
    "build_exit_inbound",
    "build_tunnel_pair",
    "validate_transport",
]

SUPPORTED_TRANSPORTS = ("reality", "ws", "grpc", "tcp")


def validate_transport(transport: str) -> str:
    if transport not in SUPPORTED_TRANSPORTS:
        raise ValueError(f"unsupported transport: {transport!r} (use one of {SUPPORTED_TRANSPORTS})")
    return transport


def default_params(transport: str) -> Dict:
    """Sensible default transport params (also used to seed a new tunnel)."""
    validate_transport(transport)
    client_id = str(uuid.uuid4())
    if transport == "reality":
        return {
            "id": client_id,
            "flow": "xtls-rprx-vision",
            "sni": "www.cloudflare.com",
            "fingerprint": "chrome",
            # In production these are generated with `xray x25519`; placeholders
            # keep the structure valid for config assembly/tests.
            "public_key": "",
            "private_key": "",
            "short_id": uuid.uuid4().hex[:8],
        }
    if transport == "ws":
        return {"id": client_id, "path": "/tunnel", "host": ""}
    if transport == "grpc":
        return {"id": client_id, "service_name": "tunnel"}
    return {"id": client_id}  # tcp


def _stream_settings(transport: str, params: Dict, *, server_side: bool) -> Dict:
    network = "tcp" if transport in ("reality", "tcp") else transport
    stream: Dict = {"network": network}

    if transport == "reality":
        stream["security"] = "reality"
        reality = {
            "show": False,
            "fingerprint": params.get("fingerprint", "chrome"),
            "serverNames": [params.get("sni", "www.cloudflare.com")],
            "shortIds": [params.get("short_id", "")],
        }
        if server_side:
            reality["privateKey"] = params.get("private_key", "")
            reality["dest"] = f'{params.get("sni", "www.cloudflare.com")}:443'
        else:
            reality["publicKey"] = params.get("public_key", "")
            reality["serverName"] = params.get("sni", "www.cloudflare.com")
        stream["realitySettings"] = reality
    elif transport == "ws":
        stream["wsSettings"] = {
            "path": params.get("path", "/tunnel"),
            "headers": ({"Host": params["host"]} if params.get("host") else {}),
        }
    elif transport == "grpc":
        stream["grpcSettings"] = {"serviceName": params.get("service_name", "tunnel")}

    return stream


def build_relay_outbound(tunnel, exit_address: str) -> Tuple[Dict, Dict]:
    """Return ``(outbound, routing_rule)`` for the relay node.

    The relay sends client traffic into ``outbound`` (a VLESS dialer to the
    exit); ``routing_rule`` pins inbound client traffic to that outbound tag.
    """
    transport = validate_transport(tunnel.transport)
    params = tunnel.params or default_params(transport)
    tag = f"tunnel-{tunnel.id}-out"

    outbound = {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": exit_address,
                    "port": int(tunnel.target_port),
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

    routing_rule = {
        "type": "field",
        "inboundTag": [f"tunnel-{tunnel.id}-in"],
        "outboundTag": tag,
    }
    return outbound, routing_rule


def build_exit_inbound(tunnel) -> Dict:
    """Return the inbound the exit node listens on for this tunnel."""
    transport = validate_transport(tunnel.transport)
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


def build_tunnel_pair(tunnel, exit_address: str) -> Dict:
    """Full config fragments for both ends of a tunnel.

    ``exit_address`` is the address the relay dials (the exit node's public
    address). Returns a dict the xray layer / API can hand to each node.
    """
    outbound, routing_rule = build_relay_outbound(tunnel, exit_address)
    return {
        "tunnel_id": tunnel.id,
        "transport": tunnel.transport,
        "relay": {
            "outbound": outbound,
            "routing_rule": routing_rule,
            "client_listen_port": int(tunnel.listen_port),
        },
        "exit": {
            "inbound": build_exit_inbound(tunnel),
        },
    }
