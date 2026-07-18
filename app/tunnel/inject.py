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

# Ports the panel host reserves for its own web/API services; a panel-local
# tunnel inbound must never try to bind these (it would crash the whole core).
try:
    from app.xray.inbound_ports import PANEL_SERVICE_HINTS

    _RESERVED_PANEL_PORTS = set(PANEL_SERVICE_HINTS)
except Exception:  # pragma: no cover - defensive
    _RESERVED_PANEL_PORTS = {80, 443, 8000}


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
        from app.tunnel import clean_public_host
        addr = clean_public_host(PANEL_PUBLIC_ADDRESS or UVICORN_HOST or "")
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
            # A NULL ``intermediate_node_id`` means "no transit hop" — it must
            # NOT be read as "the panel (node_id is None) is the transit", or
            # every 2-hop tunnel would wrongly inject transit fragments into the
            # local core (duplicate tags -> Xray refuses to start).
            transit_tunnels = [
                t for t in tunnels
                if t.intermediate_node_id is not None and t.intermediate_node_id == node_id
            ]
            exit_tunnels = [t for t in tunnels if t.exit_node_id == node_id]
            if not relay_tunnels and not transit_tunnels and not exit_tunnels:
                return result

            outbounds = result.setdefault("outbounds", [])
            inbounds = result.setdefault("inbounds", [])
            rules = result.setdefault("routing", {}).setdefault("rules", [])
            user_tags = _relay_inbound_tags(result)

            # Injection must be idempotent: re-pushing a config that already
            # carries a tunnel fragment (double apply, stale base, reconcile)
            # must never emit a duplicate inbound/outbound tag, which crashes
            # Xray with "existing tag found".
            in_tags = {ib.get("tag") for ib in inbounds if isinstance(ib, dict)}
            out_tags = {ob.get("tag") for ob in outbounds if isinstance(ob, dict)}
            inbound_port_tags: dict[int, str] = {}
            for ib in inbounds:
                if not isinstance(ib, dict):
                    continue
                port = ib.get("port")
                tag = ib.get("tag")
                if port is not None and tag:
                    inbound_port_tags[int(port)] = str(tag)

            def _add_inbound(ib) -> bool:
                tag = ib.get("tag")
                port = ib.get("port")
                # On the panel-local core, a tunnel inbound that grabs a port the
                # panel web server owns (80/443/8000) makes Xray refuse the WHOLE
                # config and take every proxy inbound down. Skip it instead so a
                # single misconfigured tunnel never crashes the core.
                if node_id is None and port in _RESERVED_PANEL_PORTS:
                    logger.warning(
                        "Tunnel inject: skipping inbound %s on reserved panel port %s "
                        "(used by the panel web server). Pick a different tunnel port "
                        "or use a dedicated node as this endpoint.",
                        tag,
                        port,
                    )
                    return False
                if node_id is None and port is not None:
                    owner = inbound_port_tags.get(int(port))
                    if owner and owner != tag and not owner.startswith("tunnel-"):
                        logger.warning(
                            "Tunnel inject: skipping inbound %s on panel port %s "
                            "(already used by inbound %s). Pick a different tunnel port.",
                            tag,
                            port,
                            owner,
                        )
                        return False
                if tag in in_tags:
                    logger.debug("Tunnel inject: inbound tag %s already present; skipping", tag)
                    return False
                in_tags.add(tag)
                if port is not None:
                    inbound_port_tags[int(port)] = str(tag)
                inbounds.append(ib)
                return True

            def _add_outbound(ob) -> bool:
                tag = ob.get("tag")
                if tag in out_tags:
                    logger.debug("Tunnel inject: outbound tag %s already present; skipping", tag)
                    return False
                out_tags.add(tag)
                outbounds.append(ob)
                return True

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
                # Already injected on this config -> its routing rule is present too.
                if not _add_outbound(tunnel_svc.build_relay_outbound(t, next_addr, next_port=next_port)):
                    continue

                sb_socks = tunnel_svc.build_singbox_bridge_socks_inbound(t)
                if _add_inbound(sb_socks):
                    rules.insert(1, tunnel_svc.build_singbox_bridge_routing_rule(t))

                relay_tags = list(user_tags)
                wg_port = (t.params or {}).get("wireguard_port")
                if wg_port:
                    from app.tunnel.relay import (
                        node_delegates_wireguard_to_tunnel,
                        wireguard_target_port,
                    )

                    # The automatic delegation breaker (app.tunnel.relay) may have
                    # suspended this relay after repeated capture failures, so
                    # native WireGuard now owns this UDP port in the kernel. Never
                    # inject the dokodemo capture in that state — Xray would fail
                    # to bind the same port and take the whole relay's core down
                    # (tunnel vs. WireGuard interference the panel must prevent).
                    if node_id is not None and not node_delegates_wireguard_to_tunnel(db, node_id):
                        logger.info(
                            "Tunnel %s: WireGuard delegation on node %s is "
                            "suspended (native WireGuard owns the port); "
                            "skipping wg-in capture inbound this restart",
                            t.id,
                            node_id,
                        )
                    else:
                        wg_inbound, _ = tunnel_svc.build_wireguard_relay_inbound(
                            t,
                            int(wg_port),
                            wg_target_port=wireguard_target_port(db, t),
                        )
                        if _add_inbound(wg_inbound):
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
                added_in = _add_inbound(tunnel_svc.build_intermediate_inbound(t))
                added_out = _add_outbound(tunnel_svc.build_intermediate_outbound(t, exit_addr))
                if added_in or added_out:
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
                _add_inbound(tunnel_svc.build_exit_inbound(t))

            # Panel exit: always keep dokodemo→127.0.0.1 WG off geoip:private
            # BLOCK; optionally pin the rest of exit traffic to WARP.
            if node_id is None and exit_tunnels:
                result = _apply_panel_exit_routing(result, db, exit_tunnels)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to inject tunnels for endpoint node_id=%s: %s", node_id, exc)
        return config

    return result


def _apply_panel_exit_routing(config, db, exit_tunnels: List) -> dict:
    """Pin panel tunnel-exit routing so WireGuard-over-tunnel can reach host wg0.

    Base Xray configs often include ``geoip:private → BLOCK``. Dokodemo on the
    relay dials ``127.0.0.1:<wg_port>`` on this host after Reality decrypt — that
    destination is private and was blackholed unless we pin localhost to DIRECT
    *before* the private-IP block (WARP-on and WARP-off alike).
    """
    from app.db.models import Node
    from app.utils import warp as warp_util
    from app.xray.warp_routing import ensure_warp_exit, is_warp_tag

    result = config if isinstance(config, dict) else dict(config)
    exit_tags = {f"tunnel-{t.id}-exit" for t in exit_tunnels}

    def _is_exit_route(rule: dict) -> bool:
        if not isinstance(rule, dict):
            return False
        inn = rule.get("inboundTag") or []
        if not isinstance(inn, list) or len(inn) != 1:
            return False
        return str(inn[0]) in exit_tags

    routing = result.setdefault("routing", {})
    rules = [r for r in list(routing.get("rules") or []) if not _is_exit_route(r)]

    warp_by_tag: dict[str, dict] = {}
    pins: list[dict] = []
    for t in exit_tunnels:
        exit_tag = f"tunnel-{t.id}-exit"
        # Always first: WG handshakes to host loopback must not hit geoip:private→BLOCK.
        pins.append(
            {
                "type": "field",
                "inboundTag": [exit_tag],
                "ip": ["127.0.0.1", "::1"],
                "outboundTag": "DIRECT",
            }
        )

        relay_id = t.relay_node_id
        if not relay_id:
            continue
        relay = db.query(Node).filter(Node.id == int(relay_id)).first()
        if relay is None or not bool(getattr(relay, "warp_enabled", False)):
            continue
        tag = (getattr(relay, "warp_tag", None) or "warp").strip() or "warp"
        if tag not in warp_by_tag:
            account = warp_util.get_warp(tag)
            outbound = (account or {}).get("outbound") if account else None
            if not isinstance(outbound, dict):
                logger.warning(
                    "Tunnel %s: relay %s wants WARP tag %s but account missing; exit stays DIRECT",
                    t.id,
                    relay_id,
                    tag,
                )
                continue
            warp_by_tag[tag] = outbound

        pins.append(
            {
                "type": "field",
                "inboundTag": [exit_tag],
                "outboundTag": tag,
            }
        )
        logger.info(
            "Panel tunnel exit %s → WARP %s (relay %s; localhost WG kept DIRECT)",
            exit_tag,
            tag,
            relay_id,
        )

    if not warp_by_tag:
        routing["rules"] = pins + rules
        result["routing"] = routing
        return result

    for tag, outbound in warp_by_tag.items():
        result = ensure_warp_exit(result, outbound, as_default_exit=False)

    routing = result.setdefault("routing", {})
    merged = [r for r in list(routing.get("rules") or []) if not _is_exit_route(r)]
    routing["rules"] = pins + merged
    result["routing"] = routing

    present = {str(o.get("tag") or "") for o in (result.get("outbounds") or [])}
    for tag, outbound in warp_by_tag.items():
        if tag not in present and is_warp_tag(tag):
            result = ensure_warp_exit(result, outbound, as_default_exit=False)
            routing = result.setdefault("routing", {})
            merged = [r for r in list(routing.get("rules") or []) if not _is_exit_route(r)]
            routing["rules"] = pins + merged
            result["routing"] = routing

    return result


# Back-compat alias for older callers / tests.
_apply_panel_exit_warp = _apply_panel_exit_routing
