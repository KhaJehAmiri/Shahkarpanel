"""Single plain-tunnel IP authority for legacy + autoscale + Finalmask.

Rules:
- ``wg_autoscale`` ON → ``WgPeer.address`` is canonical; always mirrored into
  ``proxy.settings["address"]`` so Finalmask / subscription stay consistent.
- ``wg_autoscale`` OFF → ``proxy.settings["address"]`` allocated from the node's
  configured subnet (``ensure_addresses_for_subnet`` / Finalmask plain fill).

Never allocate from ``cfg.subnet`` while autoscale owns the plain pool — that
produced mixed ``10.10.*`` (legacy) and ``10.8.*`` (autoscale slot) identities
for the same Finalmask inbound.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("nexus-wg")


def mirror_autoscale_addresses_to_proxies(db) -> int:
    """Copy ``WgPeer.address`` → ``proxy.settings["address"]``. Returns updates."""
    from app.db.models import Proxy, ProxyTypes, WgPeer

    updated = 0
    peers = db.query(WgPeer).all()
    if not peers:
        return 0

    by_user = {p.user_id: p for p in peers}
    proxies = (
        db.query(Proxy)
        .filter(Proxy.type == ProxyTypes.WireGuard, Proxy.user_id.in_(list(by_user.keys())))
        .all()
    )
    for proxy in proxies:
        peer = by_user.get(proxy.user_id)
        if peer is None or not peer.address:
            continue
        settings = dict(proxy.settings or {})
        want = peer.address
        if settings.get("address") == want:
            continue
        settings["address"] = want
        proxy.settings = settings
        updated += 1
    if updated:
        db.commit()
        logger.info("Mirrored %s autoscale WgPeer addresses into proxy.settings", updated)
    return updated


def dedupe_finalmask_peer_addresses(db) -> int:
    """Reassign duplicate ``WgPeer.address`` values so Finalmask can bill.

    Kernel WG was per-node (same ``10.10.x.y`` on every relay was fine). Finalmask
    bakes *all* peers into one Xray process — colliding ``allowedIPs`` steal
    ``user>>>email`` counters (3x-ui never has this because one inbound pool).

    Keeps the lowest ``user_id`` on each address; reallocates the rest from
    ``10.10.0.0/16`` (widened if needed). Mirrors into ``proxy.settings``.
    Returns number of peers reassigned.
    """
    from collections import defaultdict

    from app.db.models import Proxy, ProxyTypes, WgPeer
    from app.wireguard.capacity import DEFAULT_PLAIN_SUBNET, widen_subnet
    from app.wireguard.pool import WireGuardPeerIPAllocator

    rows = (
        db.query(WgPeer)
        .filter(WgPeer.address.isnot(None), WgPeer.address != "")
        .order_by(WgPeer.user_id.asc())
        .all()
    )
    by_addr: dict[str, list] = defaultdict(list)
    for peer in rows:
        host = str(peer.address).split("/")[0].strip()
        if host:
            by_addr[host].append(peer)

    collisions = {h: peers for h, peers in by_addr.items() if len(peers) > 1}
    if not collisions:
        return 0

    used = {h for h in by_addr}
    # Prefer the historical plain pool; widen until every duplicate fits.
    subnet = DEFAULT_PLAIN_SUBNET
    need = sum(len(peers) - 1 for peers in collisions.values())
    subnet = widen_subnet(subnet, min_usable=len(used) + need + 16)
    allocator = WireGuardPeerIPAllocator(subnet, used=list(used))

    reassigned = 0
    dirty_user_ids: list[int] = []
    for host, peers in collisions.items():
        # Keep the oldest user on this address.
        for peer in peers[1:]:
            new_addr = allocator.allocate()
            if not new_addr:
                logger.error(
                    "Finalmask address dedupe exhausted subnet %s (need more room)",
                    subnet,
                )
                break
            peer.address = new_addr
            dirty_user_ids.append(int(peer.user_id))
            reassigned += 1

    if not reassigned:
        return 0

    # Mirror into WireGuard proxy settings (subscription Address).
    proxies = (
        db.query(Proxy)
        .filter(
            Proxy.type == ProxyTypes.WireGuard,
            Proxy.user_id.in_(dirty_user_ids),
        )
        .all()
    )
    peer_by_uid = {
        int(p.user_id): p
        for p in db.query(WgPeer).filter(WgPeer.user_id.in_(dirty_user_ids)).all()
    }
    for proxy in proxies:
        peer = peer_by_uid.get(int(proxy.user_id))
        if peer is None or not peer.address:
            continue
        settings = dict(proxy.settings or {})
        settings["address"] = peer.address
        proxy.settings = settings

    db.commit()
    logger.warning(
        "Finalmask peer address dedupe reassigned=%s colliding_hosts=%s subnet=%s",
        reassigned,
        len(collisions),
        subnet,
    )
    return reassigned


def ensure_plain_addresses_for_finalmask(db) -> None:
    """Ensure every WG user has a plain tunnel IP when Finalmask is served."""
    from app.db import crud
    from app.wireguard.wg_manager import autoscale_enabled
    from app.wireguard.xray_native import xray_native_wg_enabled

    fm_nodes = [
        n for n in crud.get_wireguard_nodes(db)
        if n.wireguard and xray_native_wg_enabled(n.wireguard) and n.wireguard.subnet
    ]
    if not fm_nodes:
        return

    if autoscale_enabled():
        # Autoscale path owns plain IPs (WgPeer). Mirror into proxy.settings so
        # Finalmask / subscription never allocate a second identity from cfg.subnet.
        from app.wireguard.wg_manager import ensure_all_peers

        try:
            ensure_all_peers(db)
        except Exception:
            logger.exception("ensure_all_peers during Finalmask address fill failed")
        mirror_autoscale_addresses_to_proxies(db)
        try:
            dedupe_finalmask_peer_addresses(db)
        except Exception:
            logger.exception("Finalmask peer address dedupe failed")
        return

    from app.wireguard.operations import ensure_addresses_for_subnet, plain_wg_enabled

    fm_cfg = None
    for node in fm_nodes:
        cfg = node.wireguard
        if plain_wg_enabled(cfg) and cfg.subnet:
            fm_cfg = cfg
            break
        if cfg.subnet:
            fm_cfg = cfg
            break
    if fm_cfg is None:
        return
    ensure_addresses_for_subnet(db, fm_cfg.subnet, cfg=fm_cfg, for_all_wg=True)
    try:
        dedupe_finalmask_peer_addresses(db)
    except Exception:
        logger.exception("Finalmask peer address dedupe failed")
