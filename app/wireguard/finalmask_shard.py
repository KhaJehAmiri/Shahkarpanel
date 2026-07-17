"""Finalmask (Xray-native WG) peer sharding for large / unbounded user counts.

A single Xray ``wireguard`` inbound bakes every peer into ``settings.peers``.
With thousands of users that is a multi-MB config that (a) is slow to bind and
(b) can only be changed by a full core restart — which on a relay drops the
Reality tunnel and every other protocol too (the "lag + disconnect" the panel
must avoid).

Sharding splits peers across several small inbounds (``node-{id}-xray-wg-in``,
``node-{id}-xray-wg-in-1``, ...), each on its own UDP port (``base + slot``).
Every shard shares the node's server keypair, MTU, workers and Finalmask noise
so a client only needs its own port. A membership change then rebuilds only the
*one* shard the user lives in, which the reload path can hot-swap on the live
core (RemoveInbound + AddInbound) without touching the tunnel or other shards.

Slot assignment is **sticky**: once a user is placed in a slot it stays there
(stored in the WireGuard proxy's ``settings["finalmask_slot"]``) so its endpoint
port never changes underneath a working client. New users greedily fill the
lowest slot with spare capacity; a fresh slot is created only when all existing
ones are full.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nexus-wg")

# Peers per Finalmask inbound. Small enough that a single shard rebuild is cheap
# (fast bind, tiny config) yet large enough that most nodes need only a handful
# of shards. Mirrors the kernel autoscale sizing philosophy (200/iface).
FINALMASK_MAX_PEERS_PER_INBOUND = 250

# UDP ports to pre-open on the node firewall for Finalmask, counted from the
# base ``xray_wg_listen_port``. Bounds how many shards a node can grow before an
# admin must widen the range; 64 shards * 250 = 16k peers/node of headroom.
FINALMASK_SHARD_PORT_RESERVE = 64

_SETTINGS_SLOT_KEY = "finalmask_slot"


def shard_port(base_port: int, slot: int) -> int:
    """UDP port for a shard: base for slot 0, base+slot afterwards."""
    return int(base_port) + int(slot)


def shard_inbound_tag(node_id: int, slot: int) -> str:
    """Inbound tag for a shard.

    Slot 0 keeps the historical ``node-{id}-xray-wg-in`` tag so existing routing
    (WARP retarget, tunnel outbound pinning) that matches that exact tag keeps
    working; later slots append ``-{slot}``.
    """
    base = f"node-{int(node_id)}-xray-wg-in"
    return base if int(slot) == 0 else f"{base}-{int(slot)}"


def user_finalmask_slot(settings: Optional[dict]) -> int:
    """Read a user's sticky slot from WireGuard proxy settings (default 0)."""
    if not settings:
        return 0
    try:
        return max(0, int(settings.get(_SETTINGS_SLOT_KEY) or 0))
    except (TypeError, ValueError):
        return 0


def finalmask_client_port(cfg, settings: Optional[dict] = None) -> int:
    """UDP endpoint port a client should dial for its Finalmask shard."""
    base = int(getattr(cfg, "xray_wg_listen_port", 0) or 0)
    return shard_port(base, user_finalmask_slot(settings))


def ensure_finalmask_slots(db) -> Dict[int, int]:
    """Assign every WireGuard proxy a sticky Finalmask slot; return user->slot.

    Greedy bin-packing that never moves an already-placed user. Only commits
    when it actually assigns a missing slot, so repeated calls on a converged
    set are read-only.
    """
    from app.db.models import Proxy
    from app.models.proxy import ProxyTypes

    proxies = (
        db.query(Proxy)
        .filter(Proxy.type == ProxyTypes.WireGuard)
        .order_by(Proxy.user_id.asc())
        .all()
    )

    occupancy: Dict[int, int] = {}
    unassigned: List[Proxy] = []
    user_slot: Dict[int, int] = {}

    for proxy in proxies:
        settings = proxy.settings or {}
        raw = settings.get(_SETTINGS_SLOT_KEY)
        if raw is None:
            unassigned.append(proxy)
            continue
        slot = user_finalmask_slot(settings)
        occupancy[slot] = occupancy.get(slot, 0) + 1
        user_slot[proxy.user_id] = slot

    changed = 0
    for proxy in unassigned:
        slot = _lowest_open_slot(occupancy)
        occupancy[slot] = occupancy.get(slot, 0) + 1
        settings = dict(proxy.settings or {})
        settings[_SETTINGS_SLOT_KEY] = slot
        proxy.settings = settings
        user_slot[proxy.user_id] = slot
        changed += 1

    if changed:
        db.commit()
        logger.info("Assigned Finalmask shard slots to %s new WG peer(s)", changed)

    return user_slot


def _lowest_open_slot(occupancy: Dict[int, int]) -> int:
    """Lowest slot index whose occupancy is below the cap (creates new if full)."""
    slot = 0
    while occupancy.get(slot, 0) >= FINALMASK_MAX_PEERS_PER_INBOUND:
        slot += 1
    return slot


def shard_count_for_db(db) -> int:
    """Number of Finalmask shards currently in use (>=1)."""
    user_slot = ensure_finalmask_slots(db)
    if not user_slot:
        return 1
    return max(1, max(user_slot.values()) + 1)


def group_peers_by_slot(peers: List) -> Dict[int, List]:
    """Bucket ``WGUserPeer`` objects by their ``finalmask_slot`` (slot 0 always present)."""
    shards: Dict[int, List] = {0: []}
    for peer in peers:
        slot = int(getattr(peer, "finalmask_slot", 0) or 0)
        shards.setdefault(slot, []).append(peer)
    return shards


def finalmask_listen_ports(db, cfg) -> List[int]:
    """Every Finalmask UDP port to expose on the node firewall.

    Opens ``base .. base + reserve`` so a client landing on any assigned shard
    always has an open port, even for shards created after the last firewall
    sync. Bounded by :data:`FINALMASK_SHARD_PORT_RESERVE`.
    """
    base = int(getattr(cfg, "xray_wg_listen_port", 0) or 0)
    if base <= 0:
        return []
    needed = 1
    try:
        needed = shard_count_for_db(db)
    except Exception:
        needed = 1
    span = min(FINALMASK_SHARD_PORT_RESERVE, max(needed, 1))
    return [shard_port(base, slot) for slot in range(span)]
