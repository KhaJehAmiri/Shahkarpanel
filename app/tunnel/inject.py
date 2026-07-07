"""Inject tunnel fragments into a running Xray config, per endpoint.

An endpoint is either a registered node (``node_id`` is its id) or the panel's
own local Xray core (``node_id is None``). For every *enabled* tunnel where the
endpoint is the relay, we add the relay outbound + routing rule (and the
optional WireGuard-over-Reality capture inbound). For every tunnel where the
endpoint is the transit hop, we add transit inbound + outbound + routing. For
every tunnel where the endpoint is the exit, we add the exit inbound.

The result is always a fresh copy — the caller's base config (often a shared
``include_db_users()`` object passed to several nodes) is never mutated.
"""
from typing import List, Optional

from app import logger
from app import tunnel as tunnel_svc


# Bind/loopback addresses a relay can never dial as an exit endpoint.
_NON_ROUTABLE = {"", "0.0.0.0", "::", "127.0.0.1", "::1", "localhost"}


def _endpoint_address(db, node_id: Optional[int]) -> Optional[str]:
    """Reachable address the relay dials for an endpoint.

    Panel-local end -> ``PANEL_PUBLIC_ADDRESS`` (falls back to ``UVICORN_HOST``).
    Node end -> the node's ``address``.

    Returns ``None`` for panel-local when only a non-routable bind address
    (``0.0.0.0`` / ``127.0.0.1`` / ...) is available, since a relay cannot dial
    it — the caller then skips the relay side with an actionable warning.
    """
    if node_id is None:
        from config import PANEL_PUBLIC_ADDRESS, UVICORN_HOST
        addr = (PANEL_PUBLIC_ADDRESS or UVICORN_HOST or "").split(":")[0].strip()
        if addr.lower() in _NON_ROUTABLE:
            return None
        return addr or None
    from app.db.models import Node
    node = db.query(Node).filter(Node.id == node_id).first()
    return node.address if node else None


def _relay_inbound_tags(config) -> List[str]:
    """User (product) inbound tags on this endpoint to route through the tunnel.

    Uses the parsed product inbounds only, so API/excluded inbounds are never
    rerouted into the tunnel.
    """
    try:
        return list(config.inbounds_by_tag.keys())
    except AttributeError:
        return []


def apply_endpoint_tunnels(config, node_id: Optional[int]):
    """Return a copy of ``config`` with tunnel fragments for ``node_id`` injected.

    Best-effort: any failure (missing DB, bad params) is logged and the original
    base config is returned unchanged so a tunnel mistake never takes the core
    or a node offline.
    """
    from app.db import GetDB
    from app.db.models import Tunnel

    try:
        result = config.copy()
    except Exception:
        return config

    try:
        with GetDB() as db:
            tunnels = db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all()
            if not tunnels:
                return result

            relay_tunnels = [t for t in tunnels if t.relay_node_id == node_id]
            transit_tunnels = [t for t in tunnels if t.intermediate_node_id == node_id]
            exit_tunnels = [t for t in tunnels if t.exit_node_id == node_id]
            if not relay_tunnels and not transit_tunnels and not exit_tunnels:
                return result

            outbounds = result.setdefault("outbounds", [])
            inbounds = result.setdefault("inbounds", [])
            rules = result.setdefault("routing", {}).setdefault("rules", [])
            user_tags = _relay_inbound_tags(result)

            for t in relay_tunnels:
                if tunnel_svc.transport_engine(t.transport) == "singbox":
                    logger.warning(
                        "Tunnel %s: %s is a sing-box stub transport; skipping Xray relay inject",
                        t.id,
                        t.transport,
                    )
                    continue
                if t.intermediate_node_id:
                    next_id = t.intermediate_node_id
                    next_port = tunnel_svc.transit_port(t)
                else:
                    next_id = t.exit_node_id
                    next_port = int(t.target_port)
                next_addr = _endpoint_address(db, next_id)
                if not next_addr:
                    label = "transit" if t.intermediate_node_id else "exit"
                    if next_id is None:
                        logger.warning(
                            "Tunnel %s: panel is the %s but PANEL_PUBLIC_ADDRESS is "
                            "unset or non-routable (0.0.0.0/127.0.0.1). Set "
                            "PANEL_PUBLIC_ADDRESS to the panel's public IP/host. "
                            "Skipping relay side.",
                            t.id,
                            label,
                        )
                    else:
                        logger.warning(
                            "Tunnel %s: %s endpoint has no reachable address; skipping relay side",
                            t.id,
                            label,
                        )
                    continue
                outbounds.append(tunnel_svc.build_relay_outbound(t, next_addr, next_port=next_port))

                relay_tags = list(user_tags)
                wg_port = (t.params or {}).get("wireguard_port")
                if wg_port:
                    wg_inbound, _ = tunnel_svc.build_wireguard_relay_inbound(t, int(wg_port))
                    inbounds.append(wg_inbound)
                    relay_tags.append(wg_inbound["tag"])

                rules.insert(1, tunnel_svc.build_relay_routing_rule(t, relay_tags or None))

            for t in transit_tunnels:
                if tunnel_svc.transport_engine(t.transport) == "singbox":
                    continue
                exit_addr = _endpoint_address(db, t.exit_node_id)
                if not exit_addr:
                    logger.warning(
                        "Tunnel %s: exit endpoint has no reachable address; skipping transit side",
                        t.id,
                    )
                    continue
                inbounds.append(tunnel_svc.build_intermediate_inbound(t))
                outbounds.append(tunnel_svc.build_intermediate_outbound(t, exit_addr))
                rules.insert(1, tunnel_svc.build_intermediate_routing_rule(t))

            for t in exit_tunnels:
                if tunnel_svc.transport_engine(t.transport) == "singbox":
                    logger.warning(
                        "Tunnel %s: %s sing-box exit fragment not auto-injected; use GET /tunnels/%s/config",
                        t.id,
                        t.transport,
                        t.id,
                    )
                    continue
                inbounds.append(tunnel_svc.build_exit_inbound(t))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to inject tunnels for endpoint node_id=%s: %s", node_id, exc)
        return config

    return result
