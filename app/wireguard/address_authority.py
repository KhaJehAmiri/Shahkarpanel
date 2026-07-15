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
