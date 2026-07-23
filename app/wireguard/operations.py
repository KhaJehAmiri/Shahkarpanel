"""WireGuard node sync orchestration (Phase 11.3).

Glues the pure planner (``app.wireguard.sync``) to the panel->node transport
(``app.wireguard.transport``): gather the users that hold a WireGuard proxy,
build each WG node's declarative spec and push it to the connected node.

Every entry point is best-effort and never raises into the caller — WireGuard
sync must never break the Xray user lifecycle. Peer collection and spec
building are kept injectable/pure so this is unit testable with fakes.
"""
import logging
import threading
import time
from typing import Dict, List, Optional

from app.db import GetDB, crud
from app.db.models import Proxy
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.wireguard.pool import WireGuardPeerIPAllocator
from app.wireguard.sync import (WGUserPeer, amneziawg_enabled,
                                build_direct_spec, build_node_specs,
                                direct_wg_enabled, plain_wg_enabled)
from app.wireguard.transport import WireGuardTransportError, client_for_node

logger = logging.getLogger("nexus-wg")

# Users in these statuses are actively served (carry a live peer). Anything
# else (disabled / limited / expired / on_hold) is pushed as inactive so the
# node drops the peer and traffic stops immediately.
SERVED_STATUSES = (UserStatus.active,)

# Throttle for _maybe_kick_tunnel_restart: sync_node can be called often (WG
# resync loop, tunnel apply, health check, ...); restart_node rebuilds and
# pushes a full node config, so re-triggering it on every single call while
# the relay is stuck "not ready" would hammer the node instead of giving each
# attempt (and its own SSH-control-tunnel fallback) time to land.
_TUNNEL_RESTART_KICK_COOLDOWN_SEC = 30.0
_tunnel_restart_kicked_at: Dict[int, float] = {}
_tunnel_restart_kick_lock = threading.Lock()

# Coalesce user-change WG syncs. Without this, every user edit/status tick
# spawns ``@threaded_function`` work that holds a DB session through slow
# node RPC and exhausts SQLAlchemy QueuePool (idle-in-transaction → 500s).
_WG_SYNC_DEBOUNCE_SEC = 0.35
_wg_sync_lock = threading.Lock()
_wg_sync_timer: Optional[threading.Timer] = None
_wg_sync_in_flight = False
_wg_sync_queued = False


def _maybe_kick_tunnel_restart(node_id: int) -> None:
    now = time.monotonic()
    with _tunnel_restart_kick_lock:
        last = _tunnel_restart_kicked_at.get(node_id, 0.0)
        if now - last < _TUNNEL_RESTART_KICK_COOLDOWN_SEC:
            return
        _tunnel_restart_kicked_at[node_id] = now
    try:
        from app import xray

        node = xray.nodes.get(node_id)
        if node is not None and getattr(node, "connected", False):
            xray.operations.restart_node(node_id)
        else:
            xray.operations.connect_node(node_id)
    except Exception:
        logger.warning(
            "Tunnel capture self-heal restart for node %s failed to schedule",
            node_id,
            exc_info=True,
        )


def _all_wg_proxies(db) -> List[Proxy]:
    return db.query(Proxy).filter(Proxy.type == ProxyTypes.WireGuard).all()


def _settings_key_for_subnet(cfg, subnet: str) -> str:
    if cfg and getattr(cfg, "awg_subnet", None) == subnet:
        return "awg_address"
    return "address"


# Serialize "read used addresses -> pick free one -> commit" per subnet.
# Without this, two concurrent requests (e.g. two devices of the same tenant
# fetching their subscription for the first time) can both read the same
# "used" set before either commits, and both hand out the *same* free IP to
# two different users (AUDIT_FINDINGS.md M1). The panel always runs as a
# single process (see main.py: "Do NOT change workers count"), so a
# per-subnet in-process lock fully closes the race for every deployment that
# actually exists today; this mirrors the atomic-claim pattern already used
# for node connect/restart (H6/H7).
_subnet_locks_guard = threading.Lock()
_subnet_locks: Dict[str, threading.Lock] = {}


def _lock_for_subnet(subnet: str) -> threading.Lock:
    with _subnet_locks_guard:
        lock = _subnet_locks.get(subnet)
        if lock is None:
            lock = threading.Lock()
            _subnet_locks[subnet] = lock
        return lock


def ensure_user_address(db, proxy: Proxy, subnet: str, *, cfg=None) -> Optional[str]:
    """Allocate a peer IP from ``subnet`` for plain or AWG stack.

    When the subnet is full the node's configured subnet is auto-widened
    (existing peer IPs stay valid) so allocation can continue.
    """
    from app.wireguard.capacity import (
        ensure_cfg_subnet_capacity,
        ensure_interface_host_pinned,
        pinned_interface_host,
        usable_peer_slots,
    )
    from app.wireguard.kind import wg_wants_awg_address, wg_wants_plain_address

    key = _settings_key_for_subnet(cfg, subnet)
    settings = dict(proxy.settings or {})
    wants = wg_wants_awg_address if key == "awg_address" else wg_wants_plain_address
    if not wants(settings):
        return settings.get(key)
    if settings.get(key):
        return settings[key]

    # Lock by allocation family so widen+allocate stays atomic across subnet string changes.
    with _lock_for_subnet(key):
        if proxy.id is not None:
            db.refresh(proxy)
        settings = dict(proxy.settings or {})
        if settings.get(key):
            return settings[key]

        active_subnet = subnet
        if cfg is not None:
            db.refresh(cfg)
            active_subnet = cfg.awg_subnet if key == "awg_address" else cfg.subnet
            ensure_interface_host_pinned(cfg, key, db=db)

        used = [
            p.settings.get(key)
            for p in _all_wg_proxies(db)
            if p.settings and p.settings.get(key)
        ]
        used_count = len([u for u in used if u])
        pending = 1
        if usable_peer_slots(active_subnet) < used_count + pending:
            expanded = ensure_cfg_subnet_capacity(
                db,
                cfg,
                settings_key=key,
                needed_peers=used_count + pending,
            )
            if expanded:
                active_subnet = expanded

        reserved = []
        pin = pinned_interface_host(cfg, key) if cfg is not None else None
        if pin:
            reserved.append(pin)
        allocator = WireGuardPeerIPAllocator(
            active_subnet,
            used=used,
            reserved_hosts=reserved,
        )
        address = allocator.allocate()
        if not address:
            logger.warning(
                "WireGuard subnet %s exhausted; cannot allocate peer IP (key=%s)",
                active_subnet,
                key,
            )
            return None

        settings[key] = address
        proxy.settings = settings
        db.commit()
        return address


def ensure_addresses_for_subnet(
    db,
    subnet: str,
    *,
    cfg=None,
    for_all_wg: bool = False,
) -> None:
    """Allocate peer IPs for WG users missing one in ``subnet``.

    Auto-widens the node subnet when the pool would run out so bulk enables
    (thousands of users) succeed without IP collisions.

    ``for_all_wg``: allocate the plain ``address`` for every WireGuard proxy
    missing one (including amnezia-only). Used when Finalmask is enabled so
    every peer gets a stable tunnel IP in the plain pool.
    """
    from app.wireguard.capacity import (
        ensure_cfg_subnet_capacity,
        ensure_interface_host_pinned,
        pinned_interface_host,
        usable_peer_slots,
    )
    from app.wireguard.kind import wg_wants_awg_address, wg_wants_plain_address

    key = _settings_key_for_subnet(cfg, subnet)
    if for_all_wg and key == "awg_address":
        for_all_wg = False

    def _wants(settings: dict) -> bool:
        if for_all_wg and key == "address":
            return True
        return wg_wants_awg_address(settings) if key == "awg_address" else wg_wants_plain_address(settings)

    with _lock_for_subnet(key):
        if cfg is not None:
            db.refresh(cfg)
            active_subnet = cfg.awg_subnet if key == "awg_address" else cfg.subnet
            ensure_interface_host_pinned(cfg, key, db=db)
        else:
            active_subnet = subnet

        proxies = _all_wg_proxies(db)
        used = [p.settings.get(key) for p in proxies if p.settings and p.settings.get(key)]
        missing = [
            p for p in proxies
            if _wants(dict(p.settings or {})) and not (p.settings or {}).get(key)
        ]
        used_count = len([u for u in used if u])
        need = used_count + len(missing)
        if cfg is not None and usable_peer_slots(active_subnet) < need:
            expanded = ensure_cfg_subnet_capacity(
                db,
                cfg,
                settings_key=key,
                needed_peers=need,
            )
            if expanded:
                active_subnet = expanded

        reserved = []
        pin = pinned_interface_host(cfg, key) if cfg is not None else None
        if pin:
            reserved.append(pin)
        allocator = WireGuardPeerIPAllocator(
            active_subnet,
            used=used,
            reserved_hosts=reserved,
        )
        assigned = 0
        for proxy in missing:
            settings = dict(proxy.settings or {})
            address = allocator.allocate()
            if not address:
                logger.warning(
                    "WireGuard subnet %s exhausted while assigning peers (key=%s, assigned=%s, remaining=%s)",
                    active_subnet,
                    key,
                    assigned,
                    len(missing) - assigned,
                )
                break
            settings[key] = address
            proxy.settings = settings
            assigned += 1
        db.commit()
        if assigned:
            logger.info(
                "Allocated %s WireGuard peer IPs on %s (key=%s for_all_wg=%s)",
                assigned,
                active_subnet,
                key,
                for_all_wg,
            )


def ensure_plain_addresses_for_finalmask(db) -> None:
    """When any node serves Finalmask, give every WG user a plain tunnel IP.

    Delegates to ``address_authority`` so autoscale and legacy never allocate
    from different pools for the same Finalmask inbound.
    """
    from app.wireguard.address_authority import (
        ensure_plain_addresses_for_finalmask as _ensure,
    )

    _ensure(db)


def ensure_preshared_key(db, proxy: Proxy) -> dict:
    """Ensure a WireGuard proxy has a preshared key (required by AmneziaVPN on iOS)."""
    from app.wireguard.keys import generate_preshared_key

    settings = dict(proxy.settings or {})
    if not settings.get("preshared_key"):
        settings["preshared_key"] = generate_preshared_key()
        proxy.settings = settings
        db.commit()
    return settings


def collect_wg_peers_uncached(db) -> List[WGUserPeer]:
    """Build the WireGuard peer list with a single joined Proxy⋈User query.

    Prefer ``collect_wg_peers`` / ``peer_cache`` on hot paths so usage jobs do
    not re-scan tens/hundreds of thousands of rows every few seconds.
    """
    from sqlalchemy.orm import joinedload

    from app.wireguard.finalmask_shard import user_finalmask_slot

    peers: List[WGUserPeer] = []
    proxies = (
        db.query(Proxy)
        .options(joinedload(Proxy.user))
        .filter(Proxy.type == ProxyTypes.WireGuard)
        .all()
    )
    for proxy in proxies:
        settings = proxy.settings or {}
        public_key = settings.get("public_key")
        if not public_key:
            continue
        user = proxy.user
        peers.append(
            WGUserPeer(
                user_id=proxy.user_id,
                public_key=public_key,
                address=settings.get("address") or "",
                preshared_key=settings.get("preshared_key") or None,
                active=bool(user and user.status in SERVED_STATUSES),
                awg_address=settings.get("awg_address") or "",
                speed_limit_up=getattr(user, "speed_limit_up", None) if user else None,
                speed_limit_down=getattr(user, "speed_limit_down", None) if user else None,
                username=getattr(user, "username", "") or "",
                finalmask_slot=user_finalmask_slot(settings),
            )
        )
    return peers


def collect_wg_peers(db=None) -> List[WGUserPeer]:
    """Cached peer list (joinedload). Pass ``db`` to reuse an open session."""
    from app.wireguard.peer_cache import peer_cache

    return peer_cache.get_peers(db)


def _node_object(node_id: int, *, connect: bool = True):
    """Return the live connection object for a node.

    ``connect=False`` never dials — used by usage collectors so a down node
    cannot stall the 5s billing job behind SSL connect retries / the RPyC lock.
    """
    from app import xray

    node = xray.nodes.get(node_id)
    if node is None:
        return None
    conn = getattr(node, "connection", None)
    if conn is not None and not getattr(conn, "closed", True):
        return node
    if not connect:
        return None
    try:
        node.connect()
    except Exception:
        return None
    return node


def restore_relay_native_wireguard(
    db,
    dbnode,
    *,
    peers: Optional[List[WGUserPeer]] = None,
    node_object=None,
) -> bool:
    """Re-enable native WG on a relay when the Xray tunnel capture is down.

    When the tunnel still owns ``wireguard_port``, plain WG is never restored —
    that would steal the UDP port from dokodemo and permanently block Xray
    restart. AWG (separate port) may still be restored.
    """
    from app.tunnel.relay import node_delegates_wireguard_to_tunnel
    from app.wireguard.wg_manager import autoscale_enabled

    # ``connect_node``/``restart_node`` often pass a Node loaded in a session
    # that already closed; lazy-loading ``.wireguard`` then raises
    # DetachedInstanceError. Always re-bind to ``db``.
    node_id = int(getattr(dbnode, "id", dbnode))
    dbnode = crud.get_node_by_id(db, node_id)
    if dbnode is None:
        return False

    cfg = dbnode.wireguard
    if cfg is None:
        return False
    node_object = node_object if node_object is not None else _node_object(dbnode.id)
    client = client_for_node(node_object)
    if client is None:
        return False
    tunnel_owns_plain = node_delegates_wireguard_to_tunnel(db, dbnode.id)
    if peers is None:
        if plain_wg_enabled(cfg) and not tunnel_owns_plain and not autoscale_enabled():
            ensure_addresses_for_subnet(db, cfg.subnet, cfg=cfg)
        if amneziawg_enabled(cfg):
            ensure_addresses_for_subnet(db, cfg.awg_subnet, cfg=cfg)
            crud.ensure_awg_server_keys(db, dbnode)
            db.refresh(cfg)
        peers = collect_wg_peers(db)
    try:
        specs = build_node_specs(cfg, peers)
        if tunnel_owns_plain and cfg.interface:
            specs = [s for s in specs if s.get("interface") != cfg.interface]
            try:
                client.down(cfg.interface)
            except Exception:
                pass
        if not specs:
            return False
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                if node_object is not None and not getattr(node_object, "connected", False):
                    node_object.connect()
                client.apply_specs(specs)
                logger.info(
                    "Restored native WireGuard on relay node %s (tunnel relay unavailable)",
                    dbnode.id,
                )
                return True
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1)
                    try:
                        if node_object is not None:
                            node_object.disconnect()
                            node_object.connect()
                    except Exception:
                        pass
        if last_exc is not None:
            raise last_exc
        return False
    except Exception as exc:
        logger.warning(
            "Failed to restore native WireGuard on relay node %s: %s",
            dbnode.id,
            exc,
        )
        return False


def listen_udp_ports_for_cfg(cfg, db=None) -> list[int]:
    """UDP ports this WG node should expose on the public firewall.

    When Finalmask is enabled, opens the base port plus a reserved shard span
    (see ``finalmask_listen_ports``) so clients dialing ``base + slot`` succeed.
    """
    from app.wireguard.sync import (
        amneziawg_enabled,
        direct_wg_enabled,
        plain_wg_enabled,
    )
    from app.wireguard.xray_native import xray_native_wg_enabled

    ports: list[int] = []
    if cfg is None:
        return ports
    if plain_wg_enabled(cfg) and cfg.listen_port:
        ports.append(int(cfg.listen_port))
    if amneziawg_enabled(cfg) and cfg.awg_listen_port:
        ports.append(int(cfg.awg_listen_port))
    if direct_wg_enabled(cfg) and cfg.direct_listen_port:
        ports.append(int(cfg.direct_listen_port))
    if xray_native_wg_enabled(cfg) and cfg.xray_wg_listen_port:
        if db is not None:
            from app.wireguard.finalmask_shard import finalmask_listen_ports

            ports.extend(finalmask_listen_ports(db, cfg))
        else:
            # No DB: open the reserved shard span from the base port so a
            # firewall sync without a session still covers sticky slots.
            from app.wireguard.finalmask_shard import (
                FINALMASK_SHARD_PORT_RESERVE,
                shard_port,
            )

            base = int(cfg.xray_wg_listen_port)
            ports.extend(shard_port(base, slot) for slot in range(FINALMASK_SHARD_PORT_RESERVE))
    return sorted({p for p in ports if p > 0})


def open_node_listen_ports(dbnode, *, node_object=None, client=None) -> int:
    """Ask the agent to open every active WG UDP port (best-effort)."""
    cfg = dbnode.wireguard
    ports = listen_udp_ports_for_cfg(cfg)
    if not ports:
        return 0
    if client is None:
        node_object = node_object if node_object is not None else _node_object(dbnode.id)
        client = client_for_node(node_object)
    if client is None or not hasattr(client, "open_udp_ports"):
        return 0
    try:
        opened = int(client.open_udp_ports(ports) or 0)
        if opened:
            logger.info(
                "Opened UDP listen ports on node %s: %s",
                dbnode.id,
                ports,
            )
        return opened
    except Exception as exc:
        logger.warning(
            "Could not open UDP ports on node %s (%s): %s",
            dbnode.id,
            ports,
            exc,
        )
        return 0


def sync_node(db, dbnode, *, peers: Optional[List[WGUserPeer]] = None, node_object=None) -> bool:
    """Push the current peer set to one WG node. Returns True on a successful
    apply, False when the node is unconfigured/disconnected/unsupported."""
    from app.wireguard.wg_manager import autoscale_enabled

    cfg = dbnode.wireguard
    if cfg is None:
        return False

    node_object = node_object if node_object is not None else _node_object(dbnode.id)
    client = client_for_node(node_object)
    if client is None:
        return False

    if autoscale_enabled() and plain_wg_enabled(cfg):
        from app.wireguard.wg_manager import bootstrap_legacy_interfaces, sync_user_statuses

        bootstrap_legacy_interfaces(db, dbnode)
        sync_user_statuses(db, node_id=dbnode.id)

    if peers is None:
        if plain_wg_enabled(cfg) and not autoscale_enabled():
            ensure_addresses_for_subnet(db, cfg.subnet, cfg=cfg)
        if amneziawg_enabled(cfg):
            ensure_addresses_for_subnet(db, cfg.awg_subnet, cfg=cfg)
            crud.ensure_awg_server_keys(db, dbnode)
            db.refresh(cfg)
        peers = collect_wg_peers(db)

    if direct_wg_enabled(cfg):
        try:
            direct_spec = build_direct_spec(cfg, peers)
            if direct_spec:
                client.apply_specs([direct_spec])
        except Exception as exc:
            logger.warning(
                "Direct (untunneled) WireGuard sync to node %s failed: %s",
                dbnode.id,
                exc,
            )
    else:
        try:
            from app.wireguard.sync import direct_interface_name

            client.down(direct_interface_name(cfg))
        except Exception:
            pass

    # Tear down kernel interfaces that are no longer enabled (partial or full
    # disable). apply_specs only brings up listed interfaces and will not
    # remove a sibling that was turned off.
    if not plain_wg_enabled(cfg):
        try:
            if cfg.interface:
                client.down(cfg.interface)
        except Exception:
            pass
    if not amneziawg_enabled(cfg):
        try:
            if cfg.awg_interface:
                client.down(cfg.awg_interface)
        except Exception:
            pass

    try:
        from app.tunnel.relay import (
            node_delegates_wireguard_to_tunnel,
            relay_tunnel_xray_ready,
        )

        tunnel_plain_delegated = False
        if node_delegates_wireguard_to_tunnel(db, dbnode.id):
            # Tunnel owns the plain WG UDP port on this relay. Never bring
            # kernel plain WG back up here — even when Xray is temporarily
            # down — or dokodemo cannot bind and Xray stays dead (timeout).
            tunnel_plain_delegated = True
            if plain_wg_enabled(cfg):
                try:
                    if cfg.interface:
                        client.down(cfg.interface)
                except Exception:
                    pass
            xray_ready = bool(
                relay_tunnel_xray_ready(node_object, db=db, node_id=dbnode.id)
            )
            if xray_ready:
                logger.info(
                    "Plain WireGuard on relay node %s delegated to tunnel; "
                    "native plain interface stopped (AWG stays local)",
                    dbnode.id,
                )
            from app.wireguard.host_sync import sync_panel_exit_wireguard

            sync_panel_exit_wireguard(db, peers=peers)
            if not xray_ready:
                logger.warning(
                    "Relay node %s: Xray tunnel relay not running; panel exit synced "
                    "(native plain WG kept down so dokodemo can bind; AWG still applied below)",
                    dbnode.id,
                )
                # relay_tunnel_xray_ready only *observes* — it never pushes the
                # dokodemo capture inbound itself. Without an active retry here,
                # a relay that lost the capture (agent restart, prior breaker
                # trip, panel redeploy, ...) stays "not ready" forever: nothing
                # else re-attempts the config push, so the circuit breaker trips
                # on stale observation instead of a genuine failed attempt, and
                # native WireGuard never gets a chance to be replaced by the
                # tunnel again. Kick a real (background) restart so this is
                # self-healing instead of report-only.
                _maybe_kick_tunnel_restart(dbnode.id)
            # When only plain is enabled, panel-exit sync is the whole job.
            if not amneziawg_enabled(cfg):
                open_node_listen_ports(dbnode, node_object=node_object, client=client)
                return True
            # else fall through and apply AWG (and any non-plain) specs on the relay
    except Exception as exc:
        logger.warning(
            "WireGuard tunnel delegation on node %s failed: %s",
            dbnode.id,
            exc,
        )
        tunnel_plain_delegated = False

    try:
        if autoscale_enabled() and plain_wg_enabled(cfg) and amneziawg_enabled(cfg):
            awg_peers = [
                WGUserPeer(
                    user_id=p.user_id,
                    public_key=p.public_key,
                    address=p.awg_address or "",
                    preshared_key=p.preshared_key,
                    active=p.active,
                )
                for p in peers
            ]
            from app.wireguard.sync import build_node_spec, awg_params_from_cfg
            from app.wireguard.awg import AWG_RECOMMENDED_MTU

            crud.ensure_awg_server_keys(db, dbnode)
            db.refresh(cfg)
            awg_spec = build_node_spec(
                interface=cfg.awg_interface,
                listen_port=cfg.awg_listen_port,
                private_key=cfg.awg_private_key,
                subnet=cfg.awg_subnet,
                peers=awg_peers,
                mtu=AWG_RECOMMENDED_MTU,
                amnezia=awg_params_from_cfg(cfg) or None,
            )
            specs = [awg_spec]
        elif autoscale_enabled() and plain_wg_enabled(cfg):
            # Autoscale still needs the kernel interface(s) brought up on the
            # node. bootstrap_legacy_interfaces only writes DB rows; without an
            # apply here a fresh node stays silent on listen_port.
            from app.db.models import WgInterface, WgPeer
            from app.wireguard.sync import build_node_spec

            specs = []
            for iface in (
                db.query(WgInterface)
                .filter(WgInterface.node_id == dbnode.id)
                .order_by(WgInterface.slot_index)
                .all()
            ):
                iface_peers = [
                    WGUserPeer(
                        user_id=p.user_id,
                        public_key=p.public_key,
                        address=p.address or "",
                        preshared_key=p.preshared_key,
                        active=bool(p.active),
                    )
                    for p in db.query(WgPeer).filter(WgPeer.interface_id == iface.id).all()
                ]
                specs.append(
                    build_node_spec(
                        interface=iface.name,
                        listen_port=iface.listen_port,
                        private_key=iface.private_key,
                        subnet=iface.subnet,
                        peers=iface_peers,
                        mtu=cfg.mtu or 1420,
                    )
                )
            if not specs:
                # Fall back to the node config row when autoscale tables are empty.
                specs = build_node_specs(cfg, peers)
            if tunnel_plain_delegated and cfg.interface:
                specs = [s for s in specs if s.get("interface") != cfg.interface]
            if not specs:
                open_node_listen_ports(dbnode, node_object=node_object, client=client)
                return True
            client.apply_specs(specs)
            open_node_listen_ports(dbnode, node_object=node_object, client=client)
            try:
                from app.services.warp_node_sync import sync_node_warp_tproxy

                sync_node_warp_tproxy(dbnode, node_object=node_object)
            except Exception:
                logger.warning(
                    "WARP TPROXY sync after WG apply failed for node %s",
                    dbnode.id,
                    exc_info=True,
                )
            return True
        else:
            specs = build_node_specs(cfg, peers)
            if tunnel_plain_delegated and cfg.interface:
                # Never re-up plain on the relay while the tunnel owns that port.
                specs = [s for s in specs if s.get("interface") != cfg.interface]
        if not specs:
            # Xray-native-only or fully disabled: kernel ifaces already torn
            # down above; still refresh firewall for any remaining UDP ports.
            open_node_listen_ports(dbnode, node_object=node_object, client=client)
            return True
        client.apply_specs(specs)
        open_node_listen_ports(dbnode, node_object=node_object, client=client)
        try:
            from app.services.warp_node_sync import sync_node_warp_tproxy

            sync_node_warp_tproxy(dbnode, node_object=node_object)
        except Exception:
            logger.warning("WARP TPROXY sync after WG apply failed for node %s", dbnode.id, exc_info=True)
        return True
    except Exception as exc:  # best-effort: log and move on
        logger.warning("WireGuard sync to node %s failed: %s", dbnode.id, exc)
        try:
            open_node_listen_ports(dbnode, node_object=node_object, client=client)
        except Exception:
            pass
        return False


def _prepare_wg_sync(session) -> tuple[List[int], List[WGUserPeer]]:
    """DB-only prep for a full WG resync. Caller must close the session before RPC."""
    from app.wireguard.wg_manager import autoscale_enabled, ensure_all_peers

    wg_nodes = crud.get_wireguard_nodes(session)
    if not wg_nodes:
        return [], []
    if autoscale_enabled():
        try:
            ensure_all_peers(session)
        except Exception:
            # Never abort Finalmask/peer push because one autoscale race failed —
            # bulk native assign was returning sync_ok=False with empty client IPs.
            logger.exception("ensure_all_peers during WG sync prep failed")
        from app.wireguard.address_authority import mirror_autoscale_addresses_to_proxies

        try:
            mirror_autoscale_addresses_to_proxies(session)
        except Exception:
            logger.exception("mirror_autoscale_addresses_to_proxies failed")
    for n in wg_nodes:
        cfg = n.wireguard
        if cfg is None:
            continue
        if plain_wg_enabled(cfg) and not autoscale_enabled():
            ensure_addresses_for_subnet(session, cfg.subnet, cfg=cfg)
        if amneziawg_enabled(cfg):
            ensure_addresses_for_subnet(session, cfg.awg_subnet, cfg=cfg)
            crud.ensure_awg_server_keys(session, n)
        break
    ensure_plain_addresses_for_finalmask(session)
    from app.wireguard.finalmask_shard import ensure_finalmask_slots

    ensure_finalmask_slots(session)
    peers = collect_wg_peers(session)
    session.commit()
    return [n.id for n in wg_nodes], peers


def sync_all_nodes(db=None) -> int:
    """Re-sync every WireGuard node. Returns the count of successful applies."""
    from app.wireguard.host_sync import sync_panel_exit_wireguard

    # When the caller already holds a session, keep legacy behaviour (tests /
    # migration helpers). The hot user-change path always uses db=None so the
    # pool connection is released before node RPC.
    if db is not None:
        node_ids, peers = _prepare_wg_sync(db)
        count = 0
        for node_id in node_ids:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode is not None and sync_node(db, dbnode, peers=peers):
                count += 1
        if sync_panel_exit_wireguard(db, peers=peers):
            count += 1
        return count

    with GetDB() as session:
        node_ids, peers = _prepare_wg_sync(session)
    # Session closed — do not hold QueuePool slots across apply_specs / SSH.

    count = 0
    for node_id in node_ids:
        with GetDB() as session:
            dbnode = crud.get_node_by_id(session, node_id)
            if dbnode is None:
                continue
            ok = sync_node(session, dbnode, peers=peers)
            try:
                session.commit()
            except Exception:
                session.rollback()
        if ok:
            count += 1

    with GetDB() as session:
        if sync_panel_exit_wireguard(session, peers=peers):
            count += 1
            try:
                session.commit()
            except Exception:
                session.rollback()
    return count


def _run_coalesced_wg_sync() -> None:
    """Single-flight worker for debounced ``sync_user_change``."""
    global _wg_sync_in_flight, _wg_sync_queued, _wg_sync_timer
    with _wg_sync_lock:
        _wg_sync_timer = None
        if _wg_sync_in_flight:
            _wg_sync_queued = True
            return
        _wg_sync_in_flight = True
        _wg_sync_queued = False
    try:
        from app.wireguard.sync_engine import schedule_resumable_sync

        # Resumable batch sync (outbox + per-node cursor). Falls back to a
        # classic full push only when the engine cannot start.
        schedule_resumable_sync()
    except Exception as exc:
        logger.warning("WireGuard resumable sync schedule failed: %s — falling back", exc)
        try:
            sync_all_nodes()
        except Exception as exc2:
            logger.warning("WireGuard user-change sync failed: %s", exc2)
    finally:
        rerun = False
        with _wg_sync_lock:
            _wg_sync_in_flight = False
            if _wg_sync_queued:
                _wg_sync_queued = False
                rerun = True
        if rerun:
            sync_user_change()


def prepare_awg_peer_for_connect(dbnode, public_key: str) -> bool:
    """Clear a learned AWG endpoint so the client can reconnect with a new UDP port.

    Returns ``True`` once the clear request was actually delivered to the
    node (regardless of whether an endpoint needed clearing — e.g. a first
    connect is a legitimate no-op). Raises ``ValueError`` for a request that
    can never succeed as configured (no pubkey / no WG config / AWG
    disabled) and ``WireGuardTransportError`` when the node itself could not
    be reached or does not support the operation.

    Previously this silently returned ``None`` on *every* failure path, so
    the ``/wireguard/prepare`` route always answered ``{"ok": true}`` even
    when nothing happened on the node — the client believed the stale
    endpoint was cleared and reconnect kept failing (AUDIT_FINDINGS.md H2).
    """
    if not public_key:
        raise ValueError("No public key to prepare")
    cfg = dbnode.wireguard
    if cfg is None:
        raise ValueError("Node has no WireGuard configuration")
    if not amneziawg_enabled(cfg):
        raise ValueError("AmneziaWG is not enabled on this node")
    iface = cfg.awg_interface or "wg1"
    node_object = _node_object(dbnode.id)
    client = client_for_node(node_object)
    if client is None:
        raise WireGuardTransportError(f"Node {dbnode.id} is not connected")
    if not hasattr(client, "prepare_peer_for_connect"):
        raise WireGuardTransportError("Node does not support AWG endpoint prepare")
    try:
        client.prepare_peer_for_connect(iface, public_key)
    except Exception as exc:
        logger.warning("AWG peer prepare for %s failed: %s", public_key[:8], exc)
        raise WireGuardTransportError(f"Failed to prepare peer: {exc}") from exc
    return True


def sync_user_change(*, immediate: bool = False) -> None:
    """Lifecycle hook: re-sync WG nodes after any user add/update/remove.

    Schedules a resumable per-node batch sync (outbox + cursor) so large fleets
    converge without a multi-MB ``syncconf`` and can resume after disconnects.
    Debounced + single-flight to protect the SQLAlchemy pool.

    Also schedules a debounced Finalmask shard hot-replace on enabled nodes so
    the baked-in peer list matches membership without restarting Reality.

    ``immediate=True`` flushes Finalmask now (single-user create / enable).
    """
    global _wg_sync_timer, _wg_sync_queued
    try:
        from app.wireguard.finalmask_reload import (
            flush_finalmask_xray_reload,
            schedule_finalmask_xray_reload,
        )

        schedule_finalmask_xray_reload(delay=0.1 if immediate else None)
        if immediate:
            flush_finalmask_xray_reload()
    except Exception as exc:
        logger.warning("Finalmask reload schedule failed: %s", exc)
    with _wg_sync_lock:
        _wg_sync_queued = True
        if _wg_sync_timer is not None:
            _wg_sync_timer.cancel()
        delay = 0.1 if immediate else _WG_SYNC_DEBOUNCE_SEC
        timer = threading.Timer(delay, _run_coalesced_wg_sync)
        timer.daemon = True
        _wg_sync_timer = timer
        timer.start()
