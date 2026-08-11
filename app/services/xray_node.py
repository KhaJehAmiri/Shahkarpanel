"""Per-node Xray config filtering based on enabled service bindings."""
from __future__ import annotations

import logging
import socket
import threading
import time
from copy import deepcopy
from typing import FrozenSet, Optional, Set

from config import XRAY_EXCLUDE_INBOUND_TAGS, XRAY_FALLBACKS_INBOUND_TAG

logger = logging.getLogger("shahkar-xray-node")

_ADDRESS_TTL = 300.0
_address_cache: dict[str, tuple[float, FrozenSet[str]]] = {}
_address_lock = threading.Lock()

_PORT_CONFLICT_TTL = 6 * 3600.0
_port_conflicts: dict[int, dict[int, float]] = {}
_conflict_lock = threading.Lock()


def note_node_port_conflicts(node_id: int, ports) -> Set[int]:
    """Remember ports on a node that belong to another process. Returns the new ones.

    A host row only records the address clients dial. On relay servers that
    address is regularly a plain forwarder (``socat`` → panel) instead of the
    node's own core, so deriving inbounds from hosts can hand a node a port it
    must not bind. Xray refusing to bind is the one unambiguous signal, and
    without acting on it the core fails to start *at all* — the node also loses
    its tunnel capture, which was working.
    """
    added: Set[int] = set()
    now = time.monotonic()
    with _conflict_lock:
        seen = _port_conflicts.setdefault(int(node_id), {})
        for raw in ports:
            try:
                port = int(raw)
            except (TypeError, ValueError):
                continue
            if seen.get(port, 0.0) <= now:
                added.add(port)
            seen[port] = now + _PORT_CONFLICT_TTL
    return added


def node_port_conflicts(node_id: int) -> Set[int]:
    """Ports this node could not bind recently."""
    now = time.monotonic()
    with _conflict_lock:
        seen = _port_conflicts.get(int(node_id))
        if not seen:
            return set()
        live = {port: exp for port, exp in seen.items() if exp > now}
        _port_conflicts[int(node_id)] = live
        return set(live)


def node_xray_inbound_tags(db, node_id: int) -> Optional[Set[str]]:
    """Return allowed product inbound tags, or ``None`` for all inbounds.

    ``None`` means the node runs every product inbound defined on the master
    (legacy behaviour and the default ``xray`` service).

    An empty set means *no* product inbounds — used for WireGuard / sing-box
    relays that only need tunnel capture + Finalmask shards. Returning ``None``
    for those nodes used to ship the full multi-MB user config (in1/in2/…)
    over Iran paths and timed out the RPyC write (wir1-class Xray-down).

    A node that has *never* been given Xray services is not assumed to be one of
    those relays either: that assumption silently deleted the VLESS inbound from
    every node whose services had never been set, and the outage only surfaced
    later, whenever the node core happened to be restarted with the new config.
    For those nodes the enabled subscription hosts decide — a node clients are
    told to dial for an inbound has to run that inbound.

    A *disabled* binding is an answer, not a missing one: an admin who switched
    ``xray-inbound-in1`` off means it, even when hosts point at the node because
    the port is forwarded there by something outside the panel.
    """
    from app.db import crud

    bindings = crud.get_node_service_bindings(db, node_id)
    xray_bindings = [b for b in bindings if b.service and b.service.engine == "xray"]
    if not xray_bindings:
        return _tags_advertised_by_hosts(db, node_id)

    enabled = [b for b in xray_bindings if b.enabled]
    for b in enabled:
        cfg = b.service.config or {}
        if b.service.slug == "xray" or cfg.get("mode") == "all_inbounds":
            return None
        if cfg.get("inbound_tag"):
            return {str(cfg["inbound_tag"])}

    tags: Set[str] = set()
    for b in enabled:
        slug = b.service.slug
        if slug.startswith("xray-inbound-"):
            tags.add(slug[len("xray-inbound-"):])
    return tags


def _address_keys(address: Optional[str]) -> FrozenSet[str]:
    """Comparable identities of a host/node address: the name plus its IPs.

    Hosts and nodes routinely spell the same machine differently (``vl2.a.ir``
    for clients, the bare IP for the panel's own control channel), so names are
    resolved — cached, and never fatally: an unresolvable name simply matches
    nothing, which keeps a relay slim rather than guessing it serves users.
    """
    name = (address or "").strip().strip("[]").lower()
    if not name or "{" in name:
        return frozenset()

    now = time.monotonic()
    with _address_lock:
        hit = _address_cache.get(name)
        if hit and now - hit[0] < _ADDRESS_TTL:
            return hit[1]

    keys = {name}
    try:
        for info in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP):
            ip = info[4][0]
            if ip:
                keys.add(str(ip).lower())
    except OSError:
        pass

    resolved = frozenset(keys)
    with _address_lock:
        _address_cache[name] = (now, resolved)
    return resolved


def _tags_advertised_by_hosts(db, node_id: int) -> Set[str]:
    """Product inbound tags whose enabled hosts point at this node."""
    from app.db.models import Node, ProxyHost

    node = db.query(Node).filter(Node.id == node_id).first()
    node_keys = _address_keys(getattr(node, "address", None))
    if not node_keys:
        return set()

    try:
        from app import xray

        inbounds = dict(xray.config.inbounds_by_tag)
    except Exception:
        return set()

    blocked_ports = node_port_conflicts(node_id)
    tags: Set[str] = set()
    hosts = (
        db.query(ProxyHost)
        .filter(ProxyHost.is_disabled.isnot(True))
        .all()
    )
    for host in hosts:
        tag = host.inbound_tag
        if tag not in inbounds or tag in tags:
            continue
        if not node_keys & _address_keys(host.address):
            continue
        port = (inbounds.get(tag) or {}).get("port")
        if blocked_ports and port in blocked_ports:
            logger.info(
                "Node %s is advertised for %s but port %s is owned by another "
                "process there; leaving the inbound out",
                node_id,
                tag,
                port,
            )
            continue
        tags.add(tag)

    if tags:
        logger.info(
            "Node %s has no Xray service binding; serving %s because enabled hosts "
            "point at %s",
            node_id,
            ", ".join(sorted(tags)),
            node.address,
        )
    return tags


def filter_xray_config_for_node(config, allowed_tags: Optional[Set[str]]):
    """Return a copy of ``config`` keeping only allowed product inbounds."""
    if allowed_tags is None:
        return config

    try:
        from app import xray

        product_tags = set(xray.config.inbounds_by_tag.keys())
    except Exception:
        product_tags = set()

    base = config.copy() if hasattr(config, "copy") else deepcopy(dict(config))
    always_keep = set(XRAY_EXCLUDE_INBOUND_TAGS or [])
    always_keep.add("API_INBOUND")
    if XRAY_FALLBACKS_INBOUND_TAG:
        always_keep.add(XRAY_FALLBACKS_INBOUND_TAG)

    filtered = []
    for inbound in base.get("inbounds") or []:
        tag = inbound.get("tag")
        if not tag or tag in always_keep or tag not in product_tags:
            filtered.append(inbound)
        elif tag in allowed_tags:
            filtered.append(inbound)
    base["inbounds"] = filtered
    return base


def apply_node_warp_policy(cfg, dbnode):
    """Apply per-node WARP exit policy on top of the filtered master config.

    - ``warp_enabled=False`` (default): strip any inherited WARP outbounds/rules
      so the node exits via ``DIRECT`` (or whatever non-WARP routing remains).
    - ``warp_enabled=True`` + ``warp_mode=full``: catch-all exit via WARP
      (legacy behaviour) + TPROXY for kernel WG.
    - ``warp_enabled=True`` + ``warp_mode=sensitive``: only Google/YouTube/AI
      domains exit via WARP (optionally load-balanced across comma-separated
      ``warp_tag`` accounts). Same client configs/inbounds — no new links.
    """
    from app.services.warp_tproxy import (
        inject_warp_tproxy_inbound,
        retarget_xray_wg_to_warp,
        strip_warp_tproxy_inbound,
        xray_wg_outbound_tag,
    )
    from app.utils import warp as warp_util
    from app.xray.warp_routing import (
        ensure_warp_exit,
        ensure_warp_sensitive_exit,
        parse_warp_tags,
        primary_warp_tag,
        strip_warp_from_config,
    )

    raw = cfg.copy() if hasattr(cfg, "copy") else deepcopy(dict(cfg))
    data = dict(raw)
    node_id = int(getattr(dbnode, "id", 0) or 0)
    enabled = bool(getattr(dbnode, "warp_enabled", False))
    mode = str(getattr(dbnode, "warp_mode", None) or "full").strip().lower()
    if mode not in ("full", "sensitive"):
        mode = "full"
    tags = parse_warp_tags(getattr(dbnode, "warp_tag", None))

    if not enabled:
        cleaned = strip_warp_from_config(data)
        if node_id:
            cleaned = strip_warp_tproxy_inbound(cleaned, node_id)
    else:
        outbounds: list = []
        missing: list[str] = []
        for tag in tags:
            account = warp_util.get_warp(tag)
            outbound = (account or {}).get("outbound") if account else None
            if isinstance(outbound, dict):
                outbounds.append(outbound)
            else:
                missing.append(tag)
        if not outbounds:
            cleaned = strip_warp_from_config(data)
            if node_id:
                cleaned = strip_warp_tproxy_inbound(cleaned, node_id)
        elif mode == "sensitive":
            cleaned = ensure_warp_sensitive_exit(data, outbounds)
            if node_id:
                # Do not yank all Finalmask/WG onto WARP — domain rules pick
                # sensitive flows; TPROXY fallback is DIRECT.
                primary = primary_warp_tag(getattr(dbnode, "warp_tag", None))
                cleaned = inject_warp_tproxy_inbound(
                    cleaned, node_id, primary, catch_all=False
                )
        else:
            # Full catch-all: use the first available account as default exit.
            primary_ob = outbounds[0]
            cleaned = ensure_warp_exit(data, primary_ob, as_default_exit=True)
            # Extra accounts (if any) sit as alternate outbounds without
            # becoming the default exit — operators can balancer later.
            for ob in outbounds[1:]:
                cleaned = ensure_warp_exit(cleaned, ob, as_default_exit=False)
            if node_id:
                primary = str(primary_ob.get("tag") or tags[0])
                wg_out = xray_wg_outbound_tag(cleaned, node_id)
                if not (isinstance(wg_out, str) and wg_out.startswith("tunnel-")):
                    cleaned = retarget_xray_wg_to_warp(cleaned, node_id, primary)
                cleaned = inject_warp_tproxy_inbound(cleaned, node_id, primary)
        if missing:
            from app import logger

            logger.warning(
                "Node %s WARP: missing account(s) %s — using %s",
                node_id,
                ",".join(missing),
                ",".join(str(o.get("tag") or "") for o in outbounds),
            )

    raw.clear()
    raw.update(cleaned)
    return raw


def build_node_xray_config(node_id: int, base_config=None):
    """Master config + users, filtered for this node's Xray services."""
    from app import xray
    from app.db import GetDB
    from app.xray.operations import _apply_native_wireguard_inbound, _apply_node_tunnels

    if base_config is None:
        base_config = xray.config.include_db_users()

    with GetDB() as db:
        allowed = node_xray_inbound_tags(db, node_id)

    cfg = filter_xray_config_for_node(base_config, allowed)
    cfg = _apply_node_tunnels(cfg, node_id)
    cfg = _apply_native_wireguard_inbound(cfg, node_id)

    with GetDB() as db:
        from app.db import crud
        import commentjson

        dbnode = crud.get_node_by_id(db, node_id)
        raw = getattr(dbnode, "xray_config_override", None) if dbnode else None
        if raw:
            try:
                patch = commentjson.loads(raw)
                if isinstance(patch, dict):
                    cfg = _merge_node_override(cfg, patch)
            except Exception:
                pass
        if dbnode is not None:
            cfg = apply_node_warp_policy(cfg, dbnode)

    return cfg


def _merge_node_override(cfg, patch: dict):
    """Deep-merge a per-node override fragment into the effective config."""
    from app.xray.config import merge_dicts

    out = cfg.copy() if hasattr(cfg, "copy") else dict(cfg)
    for key in ("inbounds", "outbounds", "routing", "dns", "policy"):
        if key in patch:
            if isinstance(patch[key], list) and isinstance(out.get(key), list):
                out[key] = patch[key]
            elif isinstance(patch[key], dict):
                out[key] = merge_dicts(out.get(key) or {}, patch[key])
            else:
                out[key] = patch[key]
    return out
