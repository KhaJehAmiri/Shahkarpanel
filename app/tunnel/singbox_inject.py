"""Inject tunnel fragments into a sing-box node spec for relay endpoints.

Relay sing-box nodes (Hysteria2/TUIC/AnyTLS) egress through the same Xray
tunnel hop via a loopback SOCKS bridge — the node sing-box binary is often
built without ``with_utls``, so VLESS+Reality outbounds are not usable there.
"""
from typing import List, Optional

from app import logger
from app import tunnel as tunnel_svc


def build_singbox_relay_socks_outbound(tunnel) -> dict:
    """Return a sing-box SOCKS outbound that dials the relay's Xray bridge."""
    return {
        "type": "socks",
        "tag": tunnel_svc.outbound_tag(tunnel),
        "server": "127.0.0.1",
        "server_port": tunnel_svc.singbox_socks_port(tunnel),
        "version": "5",
        "udp_over_tcp": False,
    }


def build_singbox_relay_vless_outbound(
    tunnel,
    next_address: str,
    *,
    next_port: Optional[int] = None,
) -> dict:
    """Return a sing-box VLESS outbound (requires sing-box built with ``with_utls``)."""
    transport = tunnel_svc.validate_transport(tunnel.transport)
    if tunnel_svc.transport_engine(transport) != "xray":
        raise ValueError(
            f"build_singbox_relay_vless_outbound requires an xray transport, got {transport!r}"
        )
    params = tunnel.params or tunnel_svc.default_params(transport)
    port = int(next_port if next_port is not None else tunnel.target_port)

    outbound: dict = {
        "type": "vless",
        "tag": tunnel_svc.outbound_tag(tunnel),
        "server": next_address,
        "server_port": port,
        "uuid": params.get("id"),
        "packet_encoding": "xudp",
    }
    if params.get("flow"):
        outbound["flow"] = params["flow"]

    if transport == "reality":
        outbound["tls"] = {
            "enabled": True,
            "server_name": params.get("sni", "www.cloudflare.com"),
            "utls": {
                "enabled": True,
                "fingerprint": params.get("fingerprint", "chrome"),
            },
            "reality": {
                "enabled": True,
                "public_key": params.get("public_key", ""),
                "short_id": params.get("short_id", ""),
            },
        }
    elif transport == "ws":
        outbound["tls"] = {"enabled": True}
        outbound["transport"] = {
            "type": "ws",
            "path": params.get("path", "/tunnel"),
        }
        if params.get("host"):
            outbound["transport"]["headers"] = {"Host": params["host"]}
    elif transport == "grpc":
        outbound["tls"] = {"enabled": True}
        outbound["transport"] = {
            "type": "grpc",
            "service_name": params.get("service_name", "tunnel"),
        }
    elif transport == "quic":
        outbound["tls"] = {
            "enabled": True,
            "server_name": params.get("sni", "www.cloudflare.com"),
            "alpn": ["h3"],
            "insecure": True,
        }
    elif transport == "tcp":
        outbound["tls"] = {"enabled": False}

    return outbound


def _singbox_inbound_tags(spec: dict) -> List[str]:
    return [
        ib.get("tag")
        for ib in (spec.get("inbounds") or [])
        if isinstance(ib, dict) and ib.get("tag")
    ]


def apply_singbox_endpoint_tunnels(spec: dict, node_id: Optional[int]) -> dict:
    """Return a copy of ``spec`` with relay tunnel outbounds/routes for ``node_id``."""
    from app.db import GetDB
    from app.db.models import Tunnel

    result = dict(spec)
    result["inbounds"] = list(spec.get("inbounds") or [])
    result["traffic_limits"] = list(spec.get("traffic_limits") or [])

    try:
        with GetDB() as db:
            tunnels = db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all()
            relay_tunnels = [t for t in tunnels if t.relay_node_id == node_id]
            if not relay_tunnels:
                return result

            inbound_tags = _singbox_inbound_tags(result)
            if not inbound_tags:
                return result

            outbounds: List[dict] = []
            rules: List[dict] = []
            out_tags: set = set()
            primary_outbound: Optional[str] = None

            for t in relay_tunnels:
                if tunnel_svc.transport_engine(t.transport) == "singbox":
                    logger.warning(
                        "Tunnel %s: %s sing-box stub transport; skipping sing-box relay inject",
                        t.id,
                        t.transport,
                    )
                    continue
                if t.intermediate_node_id:
                    next_id = t.intermediate_node_id
                else:
                    next_id = t.exit_node_id
                next_addr = _endpoint_address(db, next_id)
                if not next_addr and next_id is not None:
                    logger.warning(
                        "Tunnel %s: next hop has no reachable address; skipping sing-box relay side",
                        t.id,
                    )
                    continue

                ob = build_singbox_relay_socks_outbound(t)
                tag = ob.get("tag")
                if tag in out_tags:
                    continue
                out_tags.add(tag)
                outbounds.append(ob)
                # sing-box 1.12+ prefers explicit route actions; keep ``outbound``
                # for older builds that still accept the legacy form.
                rules.append({
                    "inbound": list(inbound_tags),
                    "action": "route",
                    "outbound": tag,
                })
                primary_outbound = tag

            if not outbounds:
                return result

            result["tunnel_outbounds"] = outbounds
            result["tunnel_route_rules"] = rules
            result["tunnel_route_final"] = primary_outbound
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Failed to inject sing-box tunnels for endpoint node_id=%s: %s",
            node_id,
            exc,
        )
        return spec

    return result


def _endpoint_address(db, node_id: Optional[int]) -> Optional[str]:
    from app.tunnel.inject import _endpoint_address as xray_endpoint_address

    return xray_endpoint_address(db, node_id)
