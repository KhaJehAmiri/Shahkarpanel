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
import subprocess
import uuid
from typing import Dict, List, Optional, Tuple

__all__ = [
    "SUPPORTED_TRANSPORTS",
    "default_params",
    "generate_reality_keys",
    "ensure_reality_keys",
    "build_relay_outbound",
    "build_relay_routing_rule",
    "build_exit_inbound",
    "build_wireguard_relay_inbound",
    "build_tunnel_pair",
    "validate_transport",
]

SUPPORTED_TRANSPORTS = ("reality", "ws", "grpc", "tcp")


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
    return {"id": client_id}  # tcp


def _stream_settings(transport: str, params: Dict, *, server_side: bool) -> Dict:
    network = "tcp" if transport in ("reality", "tcp") else transport
    stream: Dict = {"network": network}

    if transport == "reality":
        stream["security"] = "reality"
        sni = params.get("sni", "www.cloudflare.com")
        short_id = params.get("short_id", "")
        reality = {
            "show": False,
            "fingerprint": params.get("fingerprint", "chrome"),
        }
        if server_side:
            reality["serverNames"] = [sni]
            reality["shortIds"] = [short_id]
            reality["privateKey"] = params.get("private_key", "")
            reality["dest"] = f"{sni}:443"
        else:
            reality["publicKey"] = params.get("public_key", "")
            reality["serverName"] = sni
            reality["shortId"] = short_id
        stream["realitySettings"] = reality
    elif transport == "ws":
        stream["wsSettings"] = {
            "path": params.get("path", "/tunnel"),
            "headers": ({"Host": params["host"]} if params.get("host") else {}),
        }
    elif transport == "grpc":
        stream["grpcSettings"] = {"serviceName": params.get("service_name", "tunnel")}

    return stream


def outbound_tag(tunnel) -> str:
    return f"tunnel-{tunnel.id}-out"


def build_relay_outbound(tunnel, exit_address: str) -> Dict:
    """Return the VLESS outbound the relay uses to dial the exit."""
    transport = validate_transport(tunnel.transport)
    params = tunnel.params or default_params(transport)

    return {
        "tag": outbound_tag(tunnel),
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


def build_wireguard_relay_inbound(
    tunnel,
    wg_listen_port: int,
    *,
    wg_target_address: str = "127.0.0.1",
) -> Tuple[Dict, Dict]:
    """Capture the panel's WireGuard UDP on the relay and tunnel it to the exit.

    The panel's WireGuard service is a *native* interface that runs on the exit
    end. To carry it inside Reality (rather than exposing WireGuard directly to
    Iran), the relay opens a ``dokodemo-door`` UDP inbound on the WireGuard port
    and forwards every packet, via the tunnel outbound, to the exit's WireGuard
    server (``wg_target_address``:``wg_listen_port`` — typically the exit's
    loopback, dialed by the exit's ``freedom`` outbound after decryption).

    Returns ``(inbound, routing_rule)``.
    """
    tag = f"tunnel-{tunnel.id}-wg-in"
    inbound = {
        "tag": tag,
        "listen": "0.0.0.0",
        "port": int(wg_listen_port),
        "protocol": "dokodemo-door",
        "settings": {
            "address": wg_target_address,
            "port": int(wg_listen_port),
            "network": "udp",
            "followRedirect": False,
        },
        "streamSettings": {"network": "udp"},
    }
    routing_rule = build_relay_routing_rule(tunnel, [tag])
    return inbound, routing_rule


def build_tunnel_pair(
    tunnel,
    exit_address: str,
    *,
    relay_inbound_tags: Optional[List[str]] = None,
    wireguard_port: Optional[int] = None,
) -> Dict:
    """Full config fragments for both ends of a tunnel.

    ``exit_address`` is the address the relay dials (the exit end's reachable
    address). ``relay_inbound_tags`` optionally scopes the relay routing rule to
    specific user inbounds; ``wireguard_port`` adds the WireGuard-over-Reality
    capture inbound on the relay. Returns a dict the xray layer / API hands to
    each end.
    """
    outbound = build_relay_outbound(tunnel, exit_address)
    routing_rules = [build_relay_routing_rule(tunnel, relay_inbound_tags)]

    relay: Dict = {
        "outbound": outbound,
        "routing_rule": routing_rules[0],
        "routing_rules": routing_rules,
        "client_listen_port": int(tunnel.listen_port),
    }

    if wireguard_port is not None:
        wg_inbound, wg_rule = build_wireguard_relay_inbound(tunnel, wireguard_port)
        relay["wireguard_inbound"] = wg_inbound
        routing_rules.append(wg_rule)

    return {
        "tunnel_id": tunnel.id,
        "transport": tunnel.transport,
        "relay": relay,
        "exit": {
            "inbound": build_exit_inbound(tunnel),
        },
    }
