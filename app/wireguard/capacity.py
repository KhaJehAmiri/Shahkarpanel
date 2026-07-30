"""WireGuard subnet capacity helpers.

A single ``/24`` only fits ~253 peers (gateway reserved). For panel-scale
deployments we auto-widen the node's subnet (e.g. ``10.10.0.0/24`` →
``10.10.0.0/16``) so existing peer IPs stay valid while new peers keep
getting unique addresses — no overlap, no manual re-IP of clients.

Non-aligned subnets (e.g. ``10.10.5.0/24`` → ``10.10.4.0/23``) change the
*canonical* first host. The historical interface address must stay pinned
and reserved so widen never moves the gateway or hands that IP to a peer.
"""
from __future__ import annotations

import ipaddress
import logging
from typing import List, Optional, Sequence, Union

logger = logging.getLogger("shahkar-wg")

# Floor for auto-widen. /12 ≈ 1M usable IPv4 hosts — practical "unlimited"
# for a single WG interface without crossing into multi-homed designs.
MIN_PREFIXLEN = 12

# Sensible default for new nodes (≈65k peers per stack).
DEFAULT_PLAIN_SUBNET = "10.10.0.0/16"
DEFAULT_AWG_SUBNET = "10.11.0.0/16"

_Host = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def canonical_interface_host(subnet: str) -> str:
    """First usable host of ``subnet`` (legacy gateway when the net is aligned)."""
    net = ipaddress.ip_network(subnet, strict=False)
    host = next(net.hosts(), None)
    if host is None:
        raise ValueError(f"subnet {subnet!r} has no usable host address")
    return str(host)


def _host_in_subnet(host: _Host, net: ipaddress._BaseNetwork) -> bool:
    if host not in net:
        return False
    if host == net.network_address:
        return False
    if net.version == 4 and host == net.broadcast_address:
        return False
    return True


def resolve_interface_host(subnet: str, pinned: Optional[str] = None) -> str:
    """Interface host for ``subnet``, preferring a pinned historical address.

    When ``pinned`` is still a usable host inside the (possibly widened)
    network, keep it. Otherwise fall back to the canonical first host.
    """
    net = ipaddress.ip_network(subnet, strict=False)
    if pinned:
        raw = str(pinned).split("/")[0].strip()
        try:
            host = ipaddress.ip_address(raw)
        except ValueError:
            host = None
        if host is not None and _host_in_subnet(host, net):
            return str(host)
    return canonical_interface_host(subnet)


def usable_peer_slots(subnet: str) -> int:
    """How many client peers fit after reserving the interface host."""
    net = ipaddress.ip_network(subnet, strict=False)
    # IPv4: network + broadcast + first host (server). IPv6: first host only.
    reserved = 3 if net.version == 4 else 2
    return max(0, int(net.num_addresses) - reserved)


def _supernet_one(net: ipaddress._BaseNetwork) -> ipaddress._BaseNetwork:
    return net.supernet(new_prefix=net.prefixlen - 1)


def widen_subnet(
    subnet: str,
    *,
    min_usable: int,
    avoid: Sequence[str] = (),
    min_prefix: int = MIN_PREFIXLEN,
) -> str:
    """Widen ``subnet`` until it has at least ``min_usable`` peer slots.

    Existing peer addresses remain inside the widened network. The *interface*
    host may differ from the widened net's canonical first host when the
    original subnet was not aligned — callers must pin/reserve
    ``resolve_interface_host`` from before the widen.

    Refuses to cross into any network listed in ``avoid`` (e.g. plain must not
    swallow the Amnezia subnet).
    """
    if min_usable <= 0:
        return subnet

    net = ipaddress.ip_network(subnet, strict=False)
    avoid_nets: List[ipaddress._BaseNetwork] = []
    for raw in avoid:
        if not raw:
            continue
        try:
            avoid_nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue

    if usable_peer_slots(str(net)) >= min_usable:
        return str(net)

    original = str(net)
    while usable_peer_slots(str(net)) < min_usable:
        if net.prefixlen <= min_prefix:
            logger.error(
                "WireGuard subnet %s cannot widen past /%s (need %s usable slots, have %s)",
                original,
                min_prefix,
                min_usable,
                usable_peer_slots(str(net)),
            )
            break
        candidate = _supernet_one(net)
        if any(candidate.overlaps(other) for other in avoid_nets):
            logger.error(
                "WireGuard subnet %s cannot widen to %s — overlaps sibling subnet",
                net,
                candidate,
            )
            break
        net = candidate

    widened = str(net)
    if widened != original:
        logger.info(
            "WireGuard subnet widened %s → %s (usable peers %s)",
            original,
            widened,
            usable_peer_slots(widened),
        )
    return widened


def sibling_subnets(cfg, *, excluding_key: str) -> List[str]:
    """Other subnets on the same node that must not be overlapped."""
    if cfg is None:
        return []
    out: List[str] = []
    plain = getattr(cfg, "subnet", None)
    awg = getattr(cfg, "awg_subnet", None)
    if excluding_key == "awg_address":
        if plain:
            out.append(plain)
    else:
        if awg:
            out.append(awg)
    return out


def _host_attr_for_key(settings_key: str) -> str:
    return "awg_interface_host" if settings_key == "awg_address" else "interface_host"


def _subnet_attr_for_key(settings_key: str) -> str:
    return "awg_subnet" if settings_key == "awg_address" else "subnet"


def ensure_interface_host_pinned(cfg, settings_key: str, db=None) -> Optional[str]:
    """Persist the current gateway host before any widen can move it.

    Idempotent: once ``interface_host`` / ``awg_interface_host`` is set it is
    never overwritten (so a later supernet that changes the canonical first
    host keeps the historical address).
    """
    if cfg is None:
        return None
    attr = _host_attr_for_key(settings_key)
    existing = getattr(cfg, attr, None)
    if existing:
        return str(existing).split("/")[0].strip() or None

    subnet = getattr(cfg, _subnet_attr_for_key(settings_key), None)
    if not subnet:
        return None
    try:
        pin = canonical_interface_host(subnet)
    except ValueError:
        return None
    setattr(cfg, attr, pin)
    if db is not None:
        db.add(cfg)
        db.flush()
    return pin


def pinned_interface_host(cfg, settings_key: str) -> Optional[str]:
    """Return the pinned host for this family, if any."""
    if cfg is None:
        return None
    raw = getattr(cfg, _host_attr_for_key(settings_key), None)
    if not raw:
        return None
    return str(raw).split("/")[0].strip() or None


def ensure_cfg_subnet_capacity(
    db,
    cfg,
    *,
    settings_key: str,
    needed_peers: int,
) -> Optional[str]:
    """Widen and persist the node subnet so ``needed_peers`` can be allocated.

    Pins the interface host **before** widening so a non-aligned supernet
    cannot reassign the gateway. Returns the (possibly updated) subnet
    string, or ``None`` when ``cfg`` is missing.
    """
    if cfg is None:
        return None

    if settings_key == "awg_address":
        current = cfg.awg_subnet
        attr = "awg_subnet"
    else:
        current = cfg.subnet
        attr = "subnet"

    if not current:
        return current

    # Lock gateway before supernet can change the canonical first host.
    pin = ensure_interface_host_pinned(cfg, settings_key, db=db)

    widened = widen_subnet(
        current,
        min_usable=max(1, int(needed_peers)),
        avoid=sibling_subnets(cfg, excluding_key=settings_key),
    )
    if widened != current:
        setattr(cfg, attr, widened)
        if pin:
            # Re-validate pin still sits inside the widened net (it must —
            # widen only enlarges containment).
            resolved = resolve_interface_host(widened, pin)
            if resolved != pin:
                logger.warning(
                    "WireGuard interface host pin %s not in widened %s; using %s",
                    pin,
                    widened,
                    resolved,
                )
                setattr(cfg, _host_attr_for_key(settings_key), resolved)
            logger.info(
                "WireGuard subnet %s → %s; interface host kept at %s",
                current,
                widened,
                resolve_interface_host(
                    widened,
                    getattr(cfg, _host_attr_for_key(settings_key), None),
                ),
            )
        db.add(cfg)
        db.flush()
    return widened


def guard_fleet_subnet_capacity(db, *, active_peers: int) -> None:
    """Widen every WG node's subnet when active peers exceed usable slots.

    Prevents the half-synced state seen when nodes stay on ``/24`` (~253 hosts)
    while the panel tries to push tens of thousands of peers.

    Plain pool is also required for Finalmask (``xray_wg_enabled``) even when
    kernel ``plain_enabled`` is off — subscription / allowedIPs still use
    ``proxy.settings["address"]``.
    """
    from app.db import crud
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled
    from app.wireguard.xray_native import xray_native_wg_enabled

    need = max(0, int(active_peers or 0)) + 64  # headroom
    if need <= 0:
        return
    for dbnode in crud.get_wireguard_nodes(db) or []:
        cfg = dbnode.wireguard
        if cfg is None:
            continue
        try:
            wants_plain_pool = bool(cfg.subnet) and (
                plain_wg_enabled(cfg) or xray_native_wg_enabled(cfg)
            )
            if wants_plain_pool:
                ensure_cfg_subnet_capacity(
                    db, cfg, settings_key="address", needed_peers=need
                )
            if amneziawg_enabled(cfg) and cfg.awg_subnet:
                ensure_cfg_subnet_capacity(
                    db, cfg, settings_key="awg_address", needed_peers=need
                )
        except Exception:
            logger.exception(
                "subnet capacity guard failed for node %s", getattr(dbnode, "id", "?")
            )
