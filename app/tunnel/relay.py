"""Shared helpers for relay nodes that delegate egress to a tunnel."""
import logging
import time
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Set

from app import tunnel as tunnel_svc
from app.db import crud
from app.wireguard.sync import plain_wg_enabled

logger = logging.getLogger("nexus-tunnel")

_RELAY_INDEX_TTL_SEC = 30.0
_relay_index_cache: Optional["TunnelRelayIndex"] = None
_relay_index_at: float = 0.0
_pubkey_mismatch_logged: Set[int] = set()


@dataclass(frozen=True)
class TunnelRelayIndex:
    delegate_port_by_relay: Dict[int, int]
    panel_exit_relays: FrozenSet[int]
    canonical_pubkey: Optional[str]
    relay_pubkey_by_node: Dict[int, str]


def clear_tunnel_relay_cache() -> None:
    global _relay_index_cache, _relay_index_at
    _relay_index_cache = None
    _relay_index_at = 0.0
    _pubkey_mismatch_logged.clear()


def _tunnel_relay_index(db) -> TunnelRelayIndex:
    global _relay_index_cache, _relay_index_at

    now = time.monotonic()
    if _relay_index_cache is not None and now - _relay_index_at < _RELAY_INDEX_TTL_SEC:
        return _relay_index_cache

    from app.db.models import Node, Tunnel

    delegate_port_by_relay: Dict[int, int] = {}
    panel_exit_relays: set[int] = set()
    canonical_pubkey: Optional[str] = None
    canonical_tunnel_id: Optional[int] = None
    relay_pubkey_by_node: Dict[int, str] = {}

    tunnels = db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all()
    node_ids: set[int] = set()
    for t in tunnels:
        if t.relay_node_id is not None:
            node_ids.add(int(t.relay_node_id))

    if node_ids:
        for node in db.query(Node).filter(Node.id.in_(sorted(node_ids))).all():
            cfg = node.wireguard
            if cfg is not None and getattr(cfg, "public_key", None):
                relay_pubkey_by_node[int(node.id)] = str(cfg.public_key)

    for t in sorted(tunnels, key=lambda row: int(row.id)):
        if t.relay_node_id is None:
            continue
        if tunnel_svc.transport_engine(t.transport) == "singbox":
            continue
        wg_port = (t.params or {}).get("wireguard_port")
        if not wg_port:
            continue
        relay_id = int(t.relay_node_id)
        delegate_port_by_relay.setdefault(relay_id, int(wg_port))
        if t.exit_node_id is None:
            panel_exit_relays.add(relay_id)
            pub = relay_pubkey_by_node.get(relay_id, "")
            if canonical_pubkey is None:
                canonical_pubkey = pub or None
                canonical_tunnel_id = int(t.id)
            elif pub and canonical_pubkey and pub != canonical_pubkey:
                if int(t.id) not in _pubkey_mismatch_logged:
                    _pubkey_mismatch_logged.add(int(t.id))
                    logger.warning(
                        "Tunnel %s relay WG pubkey differs from canonical panel-exit key; "
                        "subscriptions and host sync use the first tunnel's keys (tunnel %s)",
                        t.id,
                        canonical_tunnel_id,
                    )

    _relay_index_cache = TunnelRelayIndex(
        delegate_port_by_relay=delegate_port_by_relay,
        panel_exit_relays=frozenset(panel_exit_relays),
        canonical_pubkey=canonical_pubkey,
        relay_pubkey_by_node=relay_pubkey_by_node,
    )
    _relay_index_at = now
    return _relay_index_cache


def relay_wireguard_tunnel_port(db, node_id: int) -> Optional[int]:
    """Return the UDP capture port when ``node_id`` relays WG through Xray."""
    port = _tunnel_relay_index(db).delegate_port_by_relay.get(int(node_id))
    return int(port) if port is not None else None


# Automatic circuit breaker: a relay whose tunnel repeatedly fails to actually
# capture the WG port must not stay silently dead forever waiting for a human
# to disable the tunnel. After enough consecutive failures, delegation is
# suspended so native WireGuard takes the port back over automatically; it is
# retried (and, once healthy, resumed) on its own after the cooldown — no
# manual step, and never both sides fighting for the same UDP port at once.
_DELEGATION_FAIL_THRESHOLD = 3
_DELEGATION_SUSPEND_SEC = 180.0
_delegation_fail_count: Dict[int, int] = {}
_delegation_suspended_until: Dict[int, float] = {}


def record_tunnel_health(node_id: int, healthy: bool) -> None:
    """Feed a tunnel-capture health observation into the delegation breaker."""
    node_id = int(node_id)
    if healthy:
        had_state = bool(_delegation_fail_count.pop(node_id, None)) or (
            time.monotonic() < _delegation_suspended_until.pop(node_id, 0.0)
        )
        if had_state:
            logger.info(
                "Tunnel relay capture on node %s is healthy again; WireGuard "
                "delegation to the tunnel resumes",
                node_id,
            )
        return
    count = _delegation_fail_count.get(node_id, 0) + 1
    _delegation_fail_count[node_id] = count
    if count >= _DELEGATION_FAIL_THRESHOLD:
        already_suspended = time.monotonic() < _delegation_suspended_until.get(node_id, 0.0)
        _delegation_suspended_until[node_id] = time.monotonic() + _DELEGATION_SUSPEND_SEC
        if not already_suspended:
            logger.warning(
                "Tunnel relay capture on node %s failed %d times in a row; "
                "falling back to native WireGuard automatically for %.0fs "
                "(will retry the tunnel again after that)",
                node_id,
                count,
                _DELEGATION_SUSPEND_SEC,
            )


def delegation_suspended(node_id: int) -> bool:
    return time.monotonic() < _delegation_suspended_until.get(int(node_id), 0.0)


def node_delegates_wireguard_to_tunnel(db, node_id: int) -> bool:
    """True when native WG on the relay must yield the listen port to Xray.

    Returns False while the automatic breaker has this node suspended, even
    if the tunnel row is still enabled in the DB — that is what lets native
    WireGuard come back up on its own when the tunnel is broken, with no one
    having to flip a switch by hand.
    """
    if delegation_suspended(node_id):
        return False
    return relay_wireguard_tunnel_port(db, node_id) is not None


def prepare_relay_wireguard_tunnel(db, node_id: int, node_object) -> bool:
    """Stop native WG listeners on a relay before Xray captures ``wireguard_port``."""
    if not node_delegates_wireguard_to_tunnel(db, node_id):
        return False
    dbnode = crud.get_node_by_id(db, node_id)
    cfg = dbnode.wireguard if dbnode else None
    if cfg is None:
        return False
    from app.wireguard.sync import plain_wg_enabled
    from app.wireguard.transport import client_for_node

    client = client_for_node(node_object)
    if client is None:
        return False
    try:
        if plain_wg_enabled(cfg):
            client.down(cfg.interface)
        # AmneziaWG uses a separate UDP port from the tunnel's dokodemo
        # capture (plain listen_port) — leave AWG running on the relay.
        return True
    except Exception:
        return False


def ensure_tunnel_wireguard_port(db, tunnel) -> bool:
    """Seed ``params.wireguard_port`` from the relay node's plain WG listen port."""
    if tunnel.relay_node_id is None:
        return False
    if tunnel_svc.transport_engine(tunnel.transport) == "singbox":
        return False
    params = dict(tunnel.params or {})
    if params.get("wireguard_port"):
        return False

    from app.db.models import Node

    node = db.query(Node).filter(Node.id == tunnel.relay_node_id).first()
    cfg = node.wireguard if node else None
    if cfg is None or not plain_wg_enabled(cfg):
        return False

    params["wireguard_port"] = int(cfg.listen_port)
    tunnel.params = params
    return True


def panel_tunnel_exit_active(db) -> bool:
    """True when any enabled xray-engine tunnel terminates on the panel."""
    return bool(_tunnel_relay_index(db).panel_exit_relays)


def wireguard_target_port(db, tunnel) -> Optional[int]:
    """Exit-side native WireGuard listen port for dokodemo forwarding."""
    params = tunnel.params or {}
    explicit = params.get("wireguard_target_port")
    if explicit:
        return int(explicit)
    wg_port = params.get("wireguard_port")
    if not wg_port:
        return None
    if tunnel.exit_node_id is None:
        cfg = canonical_panel_exit_wireguard(db)
        if cfg is not None:
            return int(cfg.listen_port)
    return int(wg_port)


def canonical_panel_exit_wireguard(db):
    """Return the WG server row used by the panel-hosted tunnel exit."""
    from app.db.models import Node, Tunnel

    index = _tunnel_relay_index(db)
    if not index.panel_exit_relays or not index.canonical_pubkey:
        return None

    for t in sorted(
        db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all(),
        key=lambda row: int(row.id),
    ):
        if t.exit_node_id is not None or t.relay_node_id is None:
            continue
        if tunnel_svc.transport_engine(t.transport) == "singbox":
            continue
        if not (t.params or {}).get("wireguard_port"):
            continue
        node = db.query(Node).filter(Node.id == t.relay_node_id).first()
        cfg = node.wireguard if node else None
        if cfg is None or not plain_wg_enabled(cfg):
            continue
        if str(getattr(cfg, "public_key", "") or "") == (index.canonical_pubkey or ""):
            return cfg
    return None


def panel_exit_ready_for_node(db, node_id: int) -> bool:
    """For a relay whose tunnel terminates on the panel, also require the
    panel's own Xray core to actually have that tunnel's exit inbound bound.

    A relay's Xray core can answer ``fetch_xray_version`` (proving *some*
    process is alive) while the panel-exit half of the pipeline never came up
    — e.g. the panel core hadn't been restarted since the tunnel was created,
    or the exit inbound failed to bind. That leaves WireGuard silently dead
    with no automatic recovery (the exact "works on the node but no traffic
    ever arrives" failure mode). Checking the *actual* injected/booted config
    instead of merely probing liveness closes that gap.

    Tunnels that exit on a dedicated node (not the panel) return True here —
    their health is verified independently via that node's own connection.
    """
    from app.db.models import Tunnel

    port = relay_wireguard_tunnel_port(db, node_id)
    if port is None:
        return True  # this relay does not delegate WG to any tunnel

    panel_exit_tunnels = [
        t
        for t in db.query(Tunnel)
        .filter(Tunnel.enabled.is_(True), Tunnel.relay_node_id == node_id)
        .all()
        if t.exit_node_id is None and (t.params or {}).get("wireguard_port")
    ]
    if not panel_exit_tunnels:
        return True  # exits on a dedicated node, not the panel

    from app import xray

    if not xray.core.started:
        return False
    last_config = getattr(xray.core, "last_config", None)
    if last_config is None:
        return False
    try:
        tags = set(last_config.inbounds_by_tag.keys())
    except Exception:
        try:
            tags = {
                ib.get("tag")
                for ib in (last_config.get("inbounds") or [])
                if isinstance(ib, dict)
            }
        except Exception:
            logger.warning(
                "panel_exit_ready_for_node: could not read inbound tags from "
                "the live panel config for node %s (last_config type %s)",
                node_id,
                type(last_config).__name__,
            )
            return False
    expected = {f"tunnel-{t.id}-exit" for t in panel_exit_tunnels}
    ready = expected.issubset(tags)
    if not ready:
        logger.warning(
            "panel_exit_ready_for_node: node %s expects %s on the panel's live "
            "config but only found %s tunnel-tagged inbound(s): %s",
            node_id,
            sorted(expected),
            len(tags),
            sorted(t for t in tags if t and "tunnel" in str(t)),
        )
    return ready


def relay_tunnel_xray_ready(
    node_object, *, db=None, node_id: Optional[int] = None
) -> bool:
    """True when a relay node's Xray core is up and can capture WG UDP.

    This is purely observational — it does *not* feed the delegation circuit
    breaker (``record_tunnel_health``). Only an actual push attempt
    (``connect_node``/``restart_node``) has ground truth about whether the
    tunnel capture really works; recording health here too meant every
    caller that merely *checks* readiness (health-check probes, the periodic
    WG sync, ...) also voted on the breaker on its own cadence, so the same
    single underlying failure got counted 2-3x per tick and could trip the
    breaker even in the same beat a real restart attempt just succeeded.
    Callers that find this False are expected to trigger a real attempt
    (which records its own outcome) rather than relying on this call to do
    it for them.
    """
    if not node_object:
        return False
    node_alive = bool(getattr(node_object, "started", False))
    if not node_alive:
        # ``connected`` only means the RPyC control channel is up — not that
        # Xray is listening. Always probe the remote core so health-check
        # does not skip reconnect while UDP is down, or reconnect while UDP
        # is already up.
        try:
            node_alive = bool(node_object.get_version())
        except Exception:
            node_alive = False
    # Liveness alone proves *some* Xray core answers — not that the live one
    # is the tunnel-capturing config (it can be a stale native-fallback core
    # left over from before delegation was (re)granted). Mirrors the same
    # check connect_node uses before taking its "keep live core" shortcut.
    ready = node_alive and bool(getattr(node_object, "wg_tunnel_capture_active", False))
    if ready and db is not None and node_id is not None:
        try:
            ready = panel_exit_ready_for_node(db, node_id)
        except Exception:
            logger.debug(
                "panel_exit_ready_for_node check failed for node %s", node_id, exc_info=True
            )
            ready = False
    return ready


def relay_wireguard_server_public_key(
    db,
    relay_node_id: int,
    *,
    node_object=None,
) -> Optional[str]:
    """Server pubkey clients must use when connecting through a relay."""
    index = _tunnel_relay_index(db)
    relay_id = int(relay_node_id)
    if relay_id not in index.delegate_port_by_relay:
        return None
    if relay_id in index.panel_exit_relays and index.canonical_pubkey:
        # Panel-exit tunnels always terminate on the canonical wg0 key; clients
        # must not use the relay's native WG pubkey (differs per node).
        return index.canonical_pubkey
    return index.relay_pubkey_by_node.get(relay_id)
