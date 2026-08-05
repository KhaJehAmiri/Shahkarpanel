import threading
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

from sqlalchemy.exc import SQLAlchemyError

from app import logger, xray
from app.db import GetDB, crud
from app.models.node import NodeStatus
from app.models.proxy import ProxyTypes
from app.models.user import UserResponse
from app.utils.concurrency import threaded_function
from app.xray.node import XRayNode
from app.xray.serving import schedule_core_sync, sync_core_users_now, sync_main_core_user
from xray_api import XRay as XRayAPI
from xray_api.types.account import Account, XTLSFlows

if TYPE_CHECKING:
    from app.db import User as DBUser
    from app.db.models import Node as DBNode


@lru_cache(maxsize=None)
def get_tls():
    from app.db import GetDB, get_tls_certificate
    with GetDB() as db:
        tls = get_tls_certificate(db)
        return {
            "key": tls.key,
            "certificate": tls.certificate
        }


@threaded_function
def _add_user_to_inbound(api: XRayAPI, inbound_tag: str, account: Account):
    if api is None:
        return
    try:
        api.add_inbound_user(tag=inbound_tag, user=account, timeout=30)
    except (xray.exc.EmailExistsError, xray.exc.ConnectionError):
        pass


@threaded_function
def _remove_user_from_inbound(api: XRayAPI, inbound_tag: str, email: str):
    if api is None:
        return
    try:
        api.remove_inbound_user(tag=inbound_tag, email=email, timeout=5)
    except (
        xray.exc.EmailNotFoundError,
        xray.exc.ConnectionError,
        # Orphan inbound tags left after a 3x-ui migration (or deleted hosts)
        # are not present on the live core — removing against them must not
        # explode the caller thread.
        xray.exc.TagNotFoundError,
    ):
        pass


@threaded_function
def _alter_inbound_user(api: XRayAPI, inbound_tag: str, account: Account):
    if api is None:
        return
    try:
        api.remove_inbound_user(tag=inbound_tag, email=account.email, timeout=30)
    except (
        xray.exc.EmailNotFoundError,
        xray.exc.ConnectionError,
        xray.exc.TagNotFoundError,
    ):
        pass
    try:
        api.add_inbound_user(tag=inbound_tag, user=account, timeout=30)
    except (xray.exc.EmailExistsError, xray.exc.ConnectionError, xray.exc.TagNotFoundError):
        pass


def sync_core_users():
    sync_core_users_now()


@threaded_function
def sync_core_users_async(*, full: bool = False):
    schedule_core_sync(full=full)


def _sync_wireguard():
    """Best-effort: converge native WireGuard nodes after a user change."""
    try:
        from app.wireguard.operations import sync_user_change
        sync_user_change()
    except Exception:
        logger.exception("WireGuard user-change sync failed to start")
    try:
        from app.singbox.operations import sync_user_change as singbox_sync
        singbox_sync()
    except Exception:
        logger.exception("sing-box user-change sync failed to start")


def _sync_wireguard_node(node_id: int, node_object):
    """Best-effort: push WG peers and sing-box to a node that just connected."""
    try:
        from app.wireguard.sync_engine import on_node_connected

        # Resume batch sync from stored cursor (or start reconcile).
        on_node_connected(int(node_id))
    except Exception:
        logger.debug("resumable WG sync wake on connect failed", exc_info=True)
    try:
        from app.wireguard.operations import sync_node
        from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if not dbnode or dbnode.wireguard is None:
                pass
            else:
                cfg = dbnode.wireguard
                if plain_wg_enabled(cfg) or amneziawg_enabled(cfg):
                    # Bootstrap interface only when agent lacks batch API; otherwise
                    # the resumable engine fills peers without a multi-MB syncconf.
                    client_ok = False
                    try:
                        from app.wireguard.transport import client_for_node
                        client = client_for_node(node_object)
                        client_ok = bool(client and hasattr(client, "apply_batch"))
                    except Exception:
                        client_ok = False
                    if not client_ok:
                        ok = sync_node(db, dbnode, node_object=node_object)
                        if not ok:
                            logger.warning(
                                "WireGuard sync to node %s did not apply (client unavailable or no specs)",
                                node_id,
                            )
    except Exception:
        logger.exception("WireGuard sync to node %s raised", node_id)
    # A normal Xray node may *also* carry a sing-box config (Hysteria2/TUIC);
    # push it when the node connects.
    try:
        from app.singbox.operations import sync_node as singbox_sync_node

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode and dbnode.singbox is not None:
                singbox_sync_node(db, dbnode, node_object=node_object)
    except Exception:
        pass


def add_user(dbuser: "DBUser"):
    """Register user on main core (DB rebuild) and push to connected nodes."""
    schedule_core_sync()
    _push_user_to_nodes(dbuser)
    # WireGuard / Finalmask: allocate IP+slot and push to relays immediately
    # (do not wait for the core-sync debounce chain).
    try:
        has_wg = any(
            getattr(p, "type", None) == ProxyTypes.WireGuard
            or str(getattr(p, "type", "")) == "WireGuard"
            for p in (getattr(dbuser, "proxies", None) or [])
        )
        if has_wg and getattr(dbuser, "id", None) is not None:
            from app.wireguard.instant_sync import schedule_provision_and_sync_wireguard_user

            schedule_provision_and_sync_wireguard_user(int(dbuser.id))
    except Exception:
        logger.exception("WireGuard instant sync schedule failed for new user")


def _remove_user_from_inbound_sync(api: XRayAPI, inbound_tag: str, email: str):
    try:
        # Keep hot-path removes short so a hung node cannot stall the usage job.
        api.remove_inbound_user(tag=inbound_tag, email=email, timeout=5)
    except (
        xray.exc.EmailNotFoundError,
        xray.exc.ConnectionError,
        xray.exc.TagNotFoundError,
    ):
        pass


def hot_disconnect_users_on_nodes(dbusers) -> None:
    """Remove users from every connected remote node via the handler API.

    Mirrors the main-core hot path: blocks the users' new connections on each
    node with zero impact on anyone else — no ``node.restart()``. Best-effort;
    SS-2022 accounts (no gRPC CipherType) are skipped and converge on the next
    full node reconcile.
    """
    emails = {f"{u.id}.{u.username}" for u in dbusers}
    if not emails:
        return
    for node_id, node in list(xray.nodes.items()):
        live = (
            (getattr(node, "has_live_api", None) and node.has_live_api())
            or (getattr(node, "started", False) and getattr(node, "_api", None) is not None)
        )
        if not live:
            continue
        try:
            with GetDB() as db:
                from app.services.xray_node import node_xray_inbound_tags

                allowed = node_xray_inbound_tags(db, node_id)
        except Exception:
            allowed = None
        tags = allowed if allowed is not None else list(xray.config.inbounds_by_tag.keys())
        for inbound_tag in tags:
            for email in emails:
                _remove_user_from_inbound(node.api, inbound_tag, email)


def remove_user_immediate(dbuser: "DBUser"):
    """Stop serving a user immediately via the live handler API (no restart).

    Removes the user from the main core and every connected node through the
    gRPC add/remove-user path, so their new connections are blocked at once
    while everyone else stays connected. Falls back to a full-core restart only
    when the main core's API is unreachable.
    """
    from app.quota import disconnect_users_everywhere

    disconnect_users_everywhere([dbuser])


def remove_user(dbuser: "DBUser"):
    schedule_core_sync()


def _push_user_to_nodes(dbuser: "DBUser"):
    """Best-effort API push to remote Xray nodes (main core uses DB rebuild)."""
    user = UserResponse.model_validate(dbuser)
    email = f"{dbuser.id}.{dbuser.username}"
    for proxy_type, inbound_tags in user.inbounds.items():
        for inbound_tag in inbound_tags:
            inbound = xray.config.inbounds_by_tag.get(inbound_tag, {})
            try:
                proxy_settings = user.proxies[proxy_type].dict(no_obj=True)
            except KeyError:
                continue
            account = proxy_type.account_model(email=email, **proxy_settings)
            # Shadowsocks-2022 accounts have no gRPC CipherType; they reach the
            # node through full-config reload (schedule_core_sync / reconcile),
            # so skip the hot-add handler call that would raise for them.
            if getattr(account, "is_2022", False):
                continue
            if proxy_type == ProxyTypes.Trojan:
                account.flow = XTLSFlows.NONE
            elif getattr(account, 'flow', None) and (
                inbound.get('network', 'tcp') not in ('tcp', 'kcp')
                or (
                    inbound.get('network', 'tcp') in ('tcp', 'kcp')
                    and inbound.get('tls') not in ('tls', 'reality')
                )
                or inbound.get('header_type') == 'http'
            ):
                account.flow = XTLSFlows.NONE
            for node_id, node in list(xray.nodes.items()):
                if not node.connected or not node.started:
                    continue
                with GetDB() as db:
                    dbnode = crud.get_node_by_id(db, node_id)
                    if dbnode is None:
                        continue
                    from app.services.xray_node import node_xray_inbound_tags
                    allowed = node_xray_inbound_tags(db, node_id)
                    if allowed is not None and inbound_tag not in allowed:
                        continue
                    _alter_inbound_user(node.api, inbound_tag, account)


def update_user(dbuser: "DBUser"):
    schedule_core_sync()
    sync_main_core_user(dbuser)
    _push_user_to_nodes(dbuser)


def propagate_user_credential_revoke(dbuser: "DBUser") -> None:
    """After revoke_user_sub: cut live sessions and push new creds to every core."""
    try:
        from app.xray.serving import hot_disconnect_users

        hot_disconnect_users([dbuser])
    except Exception:
        logger.debug("Main-core hot disconnect failed during credential revoke", exc_info=True)
    try:
        hot_disconnect_users_on_nodes([dbuser])
    except Exception:
        logger.debug("Node hot disconnect failed during credential revoke", exc_info=True)
    update_user(dbuser)
    _sync_wireguard()


def _apply_node_tunnels(config, node_id: int):
    """Fold this node's tunnel fragments (relay/exit) into its config copy.

    Best-effort: returns the original config if injection fails so a tunnel
    misconfiguration never keeps a node from connecting.
    """
    try:
        from app.tunnel.inject import apply_endpoint_tunnels
        return apply_endpoint_tunnels(config, node_id)
    except Exception:
        return config


def _finalmask_outbound_tag(db, dbnode, node_id: int, config=None) -> str:
    """Outbound the Finalmask shards route to (tunnel > WARP > DIRECT)."""
    from app.tunnel.relay import relay_tunnel_outbound_tag

    # Prefer the tunnel outbound already injected by _apply_node_tunnels. Falling
    # back to local DIRECT/WARP is what made Finalmask bypass the Reality hop
    # while every other Xray inbound traversed it.
    outbound_tag = relay_tunnel_outbound_tag(db, node_id, config) or "DIRECT"
    if outbound_tag == "DIRECT" and dbnode and bool(getattr(dbnode, "warp_enabled", False)):
        outbound_tag = (getattr(dbnode, "warp_tag", None) or "warp").strip() or "warp"
    return outbound_tag


def _finalmask_mtu_override(db, dbnode, node_id: int) -> Optional[int]:
    """Cap Finalmask MTU on the nested tunnel (+ optional WARP) path.

    Without a cap, clients keep ``xray_wg_mtu``/1420 inside Reality and large
    TLS records black-hole after handshake — looks like "WG connects but data
    never goes through the tunnel". WARP nesting needs an even lower ceiling.
    """
    from app.tunnel.relay import relay_tunnel_outbound_tag
    from app.wireguard.xray_native import (
        TUNNEL_FINALMASK_MTU,
        TUNNEL_WARP_FINALMASK_MTU,
    )

    if not dbnode or not relay_tunnel_outbound_tag(db, node_id):
        return None
    cfg = dbnode.wireguard
    configured = int(getattr(cfg, "xray_wg_mtu", None) or 1420)
    cap = (
        TUNNEL_WARP_FINALMASK_MTU
        if bool(getattr(dbnode, "warp_enabled", False))
        else TUNNEL_FINALMASK_MTU
    )
    return min(configured, cap)


def _apply_native_wireguard_inbound(config, node_id: int):
    """Fold this WG node's Finalmask (Xray-native WG) shard inbounds into config.

    Terminates WireGuard in userspace on this node, then dispatches decrypted
    traffic like any other product inbound:

    * On a tunnel relay → ``tunnel-{id}-out`` (same Reality hop as VLESS/…);
      WARP stays on the panel/exit side of that tunnel.
    * Otherwise → ``DIRECT``, or the node's WARP tag when ``warp_enabled``.

    Peers are sharded (``app/wireguard/finalmask_shard.py``) into several small
    inbounds so a membership change rebuilds only one shard — the reload path
    can hot-swap that shard on the live core without a full restart. Every
    existing ``node-{id}-xray-wg-in*`` entry is replaced so peer IP expansions
    are always reflected.
    """
    try:
        from app.db import GetDB, crud
        from app.wireguard.operations import (
            collect_wg_peers,
            ensure_plain_addresses_for_finalmask,
        )
        from app.wireguard.finalmask_shard import ensure_finalmask_slots
        from app.wireguard.xray_native import (
            build_xray_wireguard_shards,
            xray_native_wg_enabled,
        )

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            cfg = dbnode.wireguard if dbnode else None
            if not xray_native_wg_enabled(cfg):
                return config

            ensure_plain_addresses_for_finalmask(db)
            ensure_finalmask_slots(db)
            peers = collect_wg_peers(db)
            outbound_tag = _finalmask_outbound_tag(db, dbnode, node_id, config)
            mtu_override = _finalmask_mtu_override(db, dbnode, node_id)
            inbounds, rule = build_xray_wireguard_shards(
                cfg, peers, node_id=node_id,
                outbound_tag=outbound_tag, mtu_override=mtu_override,
            )
        if not inbounds:
            return config

        shard_tags = {ib["tag"] for ib in inbounds}
        result = config.copy()
        existing = list(result.get("inbounds") or [])
        # Drop any prior Finalmask shard inbounds (tag == base or base-*) so a
        # shrunk shard set never leaves stale listeners behind.
        base_tag = f"node-{node_id}-xray-wg-in"
        existing = [
            ib for ib in existing
            if not (
                isinstance(ib, dict)
                and isinstance(ib.get("tag"), str)
                and (ib["tag"] == base_tag or ib["tag"].startswith(base_tag + "-"))
            )
        ]
        existing.extend(inbounds)
        result["inbounds"] = existing

        def _references_finalmask(r) -> bool:
            if not isinstance(r, dict):
                return False
            for t in r.get("inboundTag") or []:
                if t in shard_tags:
                    return True
                if isinstance(t, str) and (t == base_tag or t.startswith(base_tag + "-")):
                    return True
            return False

        routing = result.setdefault("routing", {})
        rules = [r for r in (routing.get("rules") or []) if not _references_finalmask(r)]
        rules.insert(0, rule)
        routing["rules"] = rules
        return result
    except Exception as exc:
        logger.warning("Failed to inject native WireGuard inbound for node %s: %s", node_id, exc)
        return config


def _apply_node_warp_exit(config, node_id: int):
    """Re-apply per-node WARP after native WG injection (keeps dokodemo + retarget)."""
    try:
        from app.db import GetDB, crud
        from app.services.xray_node import apply_node_warp_policy

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode is None:
                return config
            return apply_node_warp_policy(config, dbnode)
    except Exception as exc:
        logger.warning("Failed to apply WARP exit for node %s: %s", node_id, exc)
        return config


def remove_node(node_id: int):
    if node_id in xray.nodes:
        try:
            xray.nodes[node_id].disconnect()
        except Exception:
            pass
        finally:
            try:
                del xray.nodes[node_id]
            except KeyError:
                pass


def add_node(
    dbnode: "DBNode",
    *,
    dial_host: str | None = None,
    dial_port: int | None = None,
    dial_api_port: int | None = None,
):
    # Preserve tunnel-capture / started flags across session rebuilds so a mere
    # dial-path swap does not look like ``capture_down`` and trigger hard reconnect.
    prev = xray.nodes.get(dbnode.id)
    prev_capture = bool(getattr(prev, "wg_tunnel_capture_active", False)) if prev else False
    prev_started = bool(getattr(prev, "started", False)) if prev else False
    prev_pin = getattr(prev, "pinned_cert_sha256", None) if prev else None
    prev_observed = getattr(prev, "observed_cert_sha256", None) if prev else None

    remove_node(dbnode.id)

    tls = get_tls()
    host = (dial_host or dbnode.address or "").strip()
    port = int(dial_port if dial_port is not None else dbnode.port)
    api_port = int(dial_api_port if dial_api_port is not None else dbnode.api_port)
    node = XRayNode(
        address=host,
        port=port,
        api_port=api_port,
        ssl_key=tls["key"],
        ssl_cert=tls["certificate"],
        usage_coefficient=dbnode.usage_coefficient,
        pinned_cert_sha256=getattr(dbnode, "server_cert_sha256", None) or prev_pin,
    )
    # Tag the live node object with its DB id so callers can recover it from the
    # ``xray.nodes`` values alone (e.g. host-visibility filtering in share.py).
    try:
        node.id = dbnode.id
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        node.control_tunneled = bool(
            dial_host and dial_host.strip() in ("127.0.0.1", "localhost", "::1")
        )
    except Exception:
        pass
    if prev_capture:
        try:
            node.wg_tunnel_capture_active = True
        except Exception:
            pass
    if prev_started:
        try:
            node.started = True
        except Exception:
            pass
    if prev_observed:
        try:
            node.observed_cert_sha256 = prev_observed
        except Exception:
            pass
    xray.nodes[dbnode.id] = node

    return xray.nodes[dbnode.id]


def _control_port_reachable(host: str, port: int, *, timeout: float = 1.25) -> bool:
    """Cheap TCP probe used to prefer direct control over a sticky SSH forward."""
    import socket

    host = (host or "").strip()
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def _ssh_host_for_node(dbnode) -> str:
    """Prefer the live dial address over a stale provision_host IP.

    ``provision_host`` is the IP captured at first SSH provision; nodes that
    later move behind a DNS name (or change DC IP) keep the old value, which
    makes control-tunnel fallback hang on an unreachable host while
    ``dbnode.address`` still works.
    """
    address = (getattr(dbnode, "address", None) or "").strip()
    provision = (getattr(dbnode, "provision_host", None) or "").strip()
    if address:
        return address
    return provision


def _connect_node_session(dbnode, node):
    """Connect ``node``, falling back to an SSH control tunnel when needed."""
    # If we are already on a live control tunnel, keep it — do not dial the
    # public IP and steal the agent session back.
    if getattr(node, "control_tunneled", False):
        try:
            node.connect()
            return node
        except Exception as tun_exc:
            logger.debug(
                "Control-tunneled session connect failed for node %s: %s",
                getattr(dbnode, "id", "?"),
                tun_exc,
            )
            # fall through to rebuild / direct

    try:
        node.connect()
        return node
    except Exception as direct_exc:
        from app.control_tunnel import (
            TunnelError,
            ensure_node_tunnel,
            has_ssh_for_host,
        )

        host = _ssh_host_for_node(dbnode)
        if not has_ssh_for_host(host):
            raise ConnectionError(
                f"{direct_exc}. Direct control path failed; re-provision this "
                "node from the panel over SSH so a control tunnel can be set up."
            ) from direct_exc
        try:
            local_control, local_api = ensure_node_tunnel(
                dbnode.id,
                host,
                remote_port=dbnode.port,
                remote_api_port=dbnode.api_port,
            )
        except TunnelError as tunnel_exc:
            raise ConnectionError(
                f"{direct_exc}. Control tunnel failed: {tunnel_exc}"
            ) from direct_exc
        logger.info(
            "Node %s: using SSH control tunnel 127.0.0.1:%s (host %s)",
            dbnode.id,
            local_control,
            host,
        )
        tunneled = add_node(
            dbnode,
            dial_host="127.0.0.1",
            dial_port=local_control,
            dial_api_port=local_api,
        )
        tunneled.connect()
        return tunneled


def _prefer_control_tunnel(dbnode) -> object | None:
    """Rebuild dial target when an SSH control tunnel is already live."""
    from app.control_tunnel import dial_endpoints

    endpoints = dial_endpoints(dbnode.id)
    if not endpoints:
        return None
    host, lc, la = endpoints
    return add_node(dbnode, dial_host=host, dial_port=lc, dial_api_port=la)


def _session_for_node(dbnode, *, reason: str = "preferred path"):
    """Return a node session.

    Prefer **direct** dial when the node's public control port answers — sticky
    SSH local-forwards often accept TCP while TLS hangs, and flip-flopping
    direct↔tunnel steals the single agent session (Xray restarts on the node).
    Fall back to a live SSH control tunnel only when direct is unreachable.
    Large-payload failures still fail over via ``_force_control_tunnel_session``.
    """
    host = (getattr(dbnode, "address", None) or "").strip()
    port = int(getattr(dbnode, "port", None) or 62050)
    if _control_port_reachable(host, port):
        try:
            from app.control_tunnel import stop_node_tunnel

            stop_node_tunnel(int(dbnode.id))
        except Exception:
            pass
        return add_node(dbnode)
    preferred = _prefer_control_tunnel(dbnode)
    if preferred is not None:
        return preferred
    return add_node(dbnode)


def _force_control_tunnel_session(
    dbnode, node, *, reason: str = "large-config transfer failure"
):
    """Rebuild the node session over the SSH control tunnel.

    Used both as a fallback when the direct TLS/RPyC socket connects but drops
    mid-write on a large payload (``EOFError: stream has been closed`` on
    Iran↔abroad paths), and proactively on first connect when SSH credentials
    exist — so the panel does not keep flip-flopping direct ↔ tunnel sessions
    (each takeover restarts Xray on the node).
    """
    from app.control_tunnel import TunnelError, ensure_node_tunnel, has_ssh_for_host

    host = _ssh_host_for_node(dbnode)
    if not has_ssh_for_host(host):
        return None
    try:
        local_control, local_api = ensure_node_tunnel(
            dbnode.id,
            host,
            remote_port=dbnode.port,
            remote_api_port=dbnode.api_port,
        )
    except TunnelError as exc:
        logger.debug("Control tunnel unavailable for node %s: %s", dbnode.id, exc)
        return None
    tunneled = add_node(dbnode, dial_host="127.0.0.1", dial_port=local_control, dial_api_port=local_api)
    try:
        tunneled.connect()
    except Exception as exc:
        logger.debug("Control tunnel connect failed for node %s: %s", dbnode.id, exc)
        return None
    logger.info(
        "Node %s: using SSH control tunnel 127.0.0.1:%s (host %s) — %s",
        dbnode.id,
        local_control,
        host,
        reason,
    )
    return tunneled

def _wg_xray_degraded_message(exc: BaseException) -> str:
    return f"WireGuard active; Xray core not running: {exc}"


def _wg_node_version_label(*, xray_failed: bool, xray_version: str | None = None) -> str:
    if xray_version:
        return xray_version
    return "wireguard (xray down)" if xray_failed else "wireguard"


def _mark_wg_node_connected(
    node_id: int,
    node,
    *,
    xray_exc: BaseException | None,
    xray_version: str | None = None,
) -> str:
    """Persist connected status for a WG node; surface Xray failure without dropping RPyC."""
    version = _wg_node_version_label(xray_failed=xray_exc is not None, xray_version=xray_version)
    message = _wg_xray_degraded_message(xray_exc) if xray_exc else None
    _change_node_status(node_id, NodeStatus.connected, message=message, version=version)
    return version


def _change_node_status(node_id: int, status: NodeStatus, message: str = None, version: str = None):
    from app.events import EventType, publish

    with GetDB() as db:
        try:
            dbnode = crud.get_node_by_id(db, node_id)
            if not dbnode:
                return

            if dbnode.status == NodeStatus.disabled:
                remove_node(dbnode.id)
                return

            previous_status = dbnode.status
            crud.update_node_status(db, dbnode, status, message, version)

            # Only emit on a real transition into connected/error to avoid noise.
            if status != previous_status:
                if status == NodeStatus.connected:
                    publish(EventType.node_connected,
                            {"node_id": node_id, "name": dbnode.name, "version": version})
                elif status == NodeStatus.error:
                    publish(EventType.node_error,
                            {"node_id": node_id, "name": dbnode.name, "message": message})
        except SQLAlchemyError:
            db.rollback()


def _persist_pinned_cert(node_id: int, observed_sha256):
    """Trust-on-first-use: store the node's cert fingerprint if not pinned yet.

    Once stored, ``add_node`` feeds it back as the pin so any later cert change
    is rejected as a possible MITM. We never overwrite an existing pin here —
    a rotation is an explicit admin action.
    """
    if not observed_sha256:
        return
    with GetDB() as db:
        try:
            dbnode = crud.get_node_by_id(db, node_id)
            if not dbnode or getattr(dbnode, "server_cert_sha256", None):
                return
            dbnode.server_cert_sha256 = observed_sha256
            db.commit()
            logger.info("Pinned TLS cert for node %s (%s…)", node_id, observed_sha256[:16])
            try:
                xray.nodes[node_id].pinned_cert_sha256 = observed_sha256
            except KeyError:
                pass
        except SQLAlchemyError:
            db.rollback()


global _connecting_nodes
_connecting_nodes = {}
_connecting_nodes_lock = threading.Lock()


def _claim_connecting_node(node_id) -> bool:
    """Atomically claim the per-node connect slot.

    Returns False if another connect_node() call for this node is already
    in flight. The check-and-set must happen together under one lock — doing
    a plain ``dict.get`` followed by a later ``dict[node_id] = True`` (the
    previous implementation) leaves a TOCTOU window where two concurrent
    calls (e.g. the health-check job and a manual reconnect, or two overlapping
    health-check ticks while a slow connect is still in flight) can both pass
    the check before either sets the flag, and both proceed to call
    ``add_node``/``node.start``/``node.connect`` on the same node concurrently.
    """
    with _connecting_nodes_lock:
        if _connecting_nodes.get(node_id):
            return False
        _connecting_nodes[node_id] = True
        return True


def _release_connecting_node(node_id) -> None:
    with _connecting_nodes_lock:
        _connecting_nodes.pop(node_id, None)


def push_connected_nodes_config_sync() -> int:
    """Push fresh configs to nodes that are already connected (non-blocking connect)."""
    from app.models.node import CoreKind
    from app.services.xray_node import (
        build_node_xray_config,
        filter_xray_config_for_node,
        node_xray_inbound_tags,
    )

    pushed = 0
    with GetDB() as db:
        nodes = crud.get_nodes(db)

    for dbnode in nodes:
        node_id = dbnode.id
        node = xray.nodes.get(node_id)
        if node is None or not node.connected:
            continue
        if not _claim_connecting_node(node_id):
            continue
        try:
            config = build_node_xray_config(node_id)
            with GetDB() as db:
                allowed = node_xray_inbound_tags(db, node_id)
            config = filter_xray_config_for_node(config, allowed)
            config = _apply_node_tunnels(config, node_id)
            config = _apply_native_wireguard_inbound(config, node_id)
            config = _apply_node_warp_exit(config, node_id)

            is_wg_node = dbnode.core_kind == CoreKind.wireguard.value
            if is_wg_node:
                try:
                    node.start(config)
                except Exception as exc:
                    logger.warning(
                        'Node "%s" Xray push failed (%s); continuing WG/sing-box sync',
                        dbnode.name,
                        exc,
                    )
            else:
                node.restart(config)

            _sync_wireguard_node(node_id, node)
            pushed += 1
        except Exception as exc:
            logger.warning("push_connected_nodes_config_sync node %s failed: %s", node_id, exc)
        finally:
            _release_connecting_node(node_id)

    return pushed


def push_all_node_configs_sync() -> int:
    """Blocking push of DB user set to every node (Xray + WG + sing-box).

    Used when quota enforcement must take effect immediately — async
    ``connect_node``/``restart_node`` threads are too slow and leave limited
    users on stale node configs.
    """
    from app.models.node import CoreKind
    from app.services.xray_node import (
        build_node_xray_config,
        filter_xray_config_for_node,
        node_xray_inbound_tags,
    )

    pushed = 0
    with GetDB() as db:
        nodes = crud.get_nodes(db)

    for dbnode in nodes:
        node_id = dbnode.id
        if not _claim_connecting_node(node_id):
            continue
        try:
            try:
                node = xray.nodes[node_id]
                if not node.connected:
                    raise KeyError
            except KeyError:
                node = _session_for_node(dbnode, reason="bulk config push")

            if not node.connected:
                node = _connect_node_session(dbnode, node)

            config = build_node_xray_config(node_id)
            with GetDB() as db:
                allowed = node_xray_inbound_tags(db, node_id)
            config = filter_xray_config_for_node(config, allowed)
            config = _apply_node_tunnels(config, node_id)
            config = _apply_native_wireguard_inbound(config, node_id)
            config = _apply_node_warp_exit(config, node_id)

            is_wg_node = dbnode.core_kind == CoreKind.wireguard.value
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    if is_wg_node:
                        node.start(config)
                    else:
                        node.restart(config)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc).lower()
                    # Large configs often drop the direct RPyC stream on
                    # Iran↔abroad paths — retry via SSH control tunnel, then
                    # a fresh direct session.
                    if attempt >= 2 or not (
                        "stream has been closed" in msg
                        or "eof" in msg
                        or "result expired" in msg
                    ):
                        break
                    forced = _force_control_tunnel_session(dbnode, node)
                    if forced is not None:
                        node = forced
                        logger.info(
                            'Node "%s" retrying Xray push via control tunnel (attempt %s)',
                            dbnode.name,
                            attempt + 2,
                        )
                        continue
                    try:
                        if node_id in xray.nodes:
                            try:
                                xray.nodes[node_id].disconnect()
                            except Exception:
                                pass
                            xray.nodes.pop(node_id, None)
                        node = _session_for_node(dbnode, reason="fresh session after push fail")
                        node = _connect_node_session(dbnode, node)
                        logger.info(
                            'Node "%s" retrying Xray push on fresh session (attempt %s)',
                            dbnode.name,
                            attempt + 2,
                        )
                    except Exception:
                        pass
            if last_exc is not None:
                if is_wg_node:
                    logger.warning(
                        'Node "%s" Xray push failed (%s); continuing WG/sing-box sync',
                        dbnode.name,
                        last_exc,
                    )
                    if not node.connected:
                        try:
                            node.connect()
                        except Exception:
                            pass
                else:
                    raise last_exc

            _sync_wireguard_node(node_id, node)
            pushed += 1
        except Exception as exc:
            logger.warning("push_all_node_configs_sync node %s failed: %s", node_id, exc)
        finally:
            _release_connecting_node(node_id)

    return pushed


@threaded_function
def connect_node(node_id, config=None):
    if not _claim_connecting_node(node_id):
        return

    dbnode = None
    try:
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)

        if not dbnode:
            return

        from app.models.node import NodeStatus as _NodeStatus

        if dbnode.status == _NodeStatus.disabled:
            # Drop any stale live session so health checks stop hammering a
            # node the operator explicitly took offline.
            try:
                stale = xray.nodes.pop(dbnode.id, None)
                if stale is not None:
                    try:
                        stale.disconnect()
                    except Exception:
                        pass
            except Exception:
                pass
            return

        try:
            node = xray.nodes[dbnode.id]
            if not node.connected:
                raise KeyError
        except KeyError:
            node = _session_for_node(dbnode, reason="preferred path")

        # Skip soft refresh while a Finalmask hot-replace holds the RPyC
        # channel — preempting it is what flips nodes connecting↔connected.
        try:
            from app.wireguard.sync_engine import is_finalmask_rpc_busy

            if is_finalmask_rpc_busy(node_id):
                logger.debug(
                    "Skipping connect_node for \"%s\": node RPC busy (WG apply)",
                    dbnode.name,
                )
                return
        except Exception:
            pass

        need_connect = True
        if node.connected:
            try:
                node.get_version()
                need_connect = False
            except Exception:
                pass
        # Soft reconnect: if the UI already shows connected, do NOT flip to
        # "connecting" for a session refresh. Concurrent health/WG jobs used to
        # advertise connecting on every RPyC blip, which looked like a flap.
        # Only surface connecting when coming from a non-connected state.
        prev_status = getattr(dbnode, "status", None)
        if need_connect:
            from app.models.node import NodeStatus as _NS

            soft = prev_status == _NS.connected
            if not soft:
                _change_node_status(node_id, NodeStatus.connecting)
                logger.info(f"Connecting to \"{dbnode.name}\" node")
            else:
                logger.debug(
                    "Refreshing RPyC session for \"%s\" without UI connecting flap",
                    dbnode.name,
                )
            try:
                node = _connect_node_session(dbnode, node)
            except Exception:
                node = _session_for_node(dbnode, reason="reconnect after session failure")
                node = _connect_node_session(dbnode, node)
        else:
            logger.debug("Reusing live RPyC session for \"%s\"", dbnode.name)

        from app.models.node import CoreKind

        is_wg_node = dbnode.core_kind == CoreKind.wireguard.value
        version = None
        degraded_msg = None
        delegates_tunnel = False
        xray_wg_enabled = False
        kept_live = False
        hard_reconnect = False
        if is_wg_node:
            with GetDB() as db:
                from app.db.models import NodeWireGuard
                from app.tunnel.relay import (
                    node_delegates_wireguard_to_tunnel,
                    prepare_relay_wireguard_tunnel,
                )

                delegates_tunnel = node_delegates_wireguard_to_tunnel(db, node_id)
                wg_row = (
                    db.query(NodeWireGuard.xray_wg_enabled)
                    .filter(NodeWireGuard.node_id == node_id)
                    .first()
                )
                xray_wg_enabled = bool(wg_row[0]) if wg_row else False
            # Hard reconnect only when the node was actually down / degraded.
            # A missing in-memory ``wg_tunnel_capture_active`` after session
            # rebuild used to force full Xray re-push + tunnel re-apply on a
            # healthy core — that is the main Iran↔abroad flap loop.
            prefer_keep_live = bool(delegates_tunnel or xray_wg_enabled)
            from app.models.node import NodeStatus as _NSKeep

            msg = (getattr(dbnode, "message", None) or "").strip().lower()
            degraded = (
                "degraded" in msg
                or "xray down" in msg
                or "failed to connect" in msg
                or "not connected" in msg
            )
            capture_flag = bool(getattr(node, "wg_tunnel_capture_active", False))
            was_connected = prev_status == _NSKeep.connected
            # Only treat capture as hard-fail when we also have evidence the
            # core is unhealthy — not when the flag alone was cleared.
            hard_reconnect = (not was_connected) or degraded
            try:
                if not node.connected:
                    node.connect()
                if delegates_tunnel:
                    with GetDB() as db:
                        prepare_relay_wireguard_tunnel(db, node_id, node)
                version = node.get_version()
                if version and prefer_keep_live and not hard_reconnect:
                    if delegates_tunnel:
                        node.wg_tunnel_capture_active = True
                    try:
                        node.started = True
                    except Exception:
                        pass
                    kept_live = True
                    if delegates_tunnel and not capture_flag:
                        logger.info(
                            "WireGuard node \"%s\" soft-restored tunnel capture "
                            "flag (Xray live %s) — skip hard reconnect",
                            dbnode.name,
                            version,
                        )
                    else:
                        logger.info(
                            "WireGuard node \"%s\" keeping live Xray (%s)",
                            dbnode.name,
                            version,
                        )
                elif version and prefer_keep_live and hard_reconnect:
                    logger.info(
                        "WireGuard node \"%s\" hard reconnect — re-pushing "
                        "Xray/tunnel config (was status=%s degraded=%s "
                        "capture_flag=%s)",
                        dbnode.name,
                        getattr(prev_status, "value", prev_status),
                        degraded,
                        capture_flag,
                    )
            except Exception:
                version = None
                kept_live = False

        if not kept_live:
            if config is None:
                from app.services.xray_node import build_node_xray_config
                config = build_node_xray_config(node_id)
            else:
                from app.services.xray_node import filter_xray_config_for_node, node_xray_inbound_tags
                with GetDB() as db:
                    allowed = node_xray_inbound_tags(db, node_id)
                config = filter_xray_config_for_node(config, allowed)
                config = _apply_node_tunnels(config, node_id)
                config = _apply_native_wireguard_inbound(config, node_id)
                config = _apply_node_warp_exit(config, node_id)

        if is_wg_node:
            # WireGuard nodes need the RPyC channel for wg_apply; Xray on the
            # node is best-effort (stats/API) and must not block AWG sync.
            xray_exc = None
            if kept_live:
                xray_exc = None
            elif delegates_tunnel:
                # We already decided not to keep-live (hard reconnect / no version).
                # Always push the built config so tunnel dokodemo + outbounds land —
                # do not re-enter keep-live just because get_version() answers.
                for attempt in range(3):
                    try:
                        if not node.connected:
                            node.connect()
                        with GetDB() as db:
                            prepare_relay_wireguard_tunnel(db, node_id, node)
                        try:
                            node.start(config)
                        except Exception:
                            node.restart(config)
                        version = node.get_version()
                        node.wg_tunnel_capture_active = True
                        xray_exc = None
                        logger.info(
                            "WireGuard node \"%s\" Xray/tunnel config applied (%s)",
                            dbnode.name,
                            version,
                        )
                        break
                    except Exception as exc:
                        xray_exc = exc
                        logger.warning(
                            "WireGuard node \"%s\" Xray start attempt %d failed (%s)",
                            dbnode.name,
                            attempt + 1,
                            exc,
                        )
                        if attempt < 2:
                            time.sleep(1)
                            try:
                                node.disconnect()
                            except Exception:
                                pass
                            if attempt == 0 and not getattr(node, "control_tunneled", False):
                                # A direct socket that connects but drops mid-write on
                                # a large tunnel/Finalmask config retries into the exact
                                # same failure every time. Route through SSH instead of
                                # blindly reconnecting on the same unreliable path.
                                forced = _force_control_tunnel_session(dbnode, node)
                                if forced is not None:
                                    node = forced
            else:
                # Non-Finalmask wireguard-core nodes (VLESS tunnel exits): always
                # apply the built config so restored/reseller users converge.
                for attempt in range(3):
                    try:
                        if not node.connected:
                            node.connect()
                        try:
                            node.start(config)
                        except Exception:
                            node.restart(config)
                        version = node.get_version()
                        node.wg_tunnel_capture_active = False
                        xray_exc = None
                        logger.info(
                            "WireGuard node \"%s\" Xray config applied (%s)",
                            dbnode.name,
                            version,
                        )
                        break
                    except Exception as exc:
                        xray_exc = exc
                        logger.warning(
                            "WireGuard node \"%s\" Xray start attempt %d failed (%s)",
                            dbnode.name,
                            attempt + 1,
                            exc,
                        )
                        if attempt < 2:
                            time.sleep(1)
                        try:
                            node.disconnect()
                        except Exception:
                            pass
            if delegates_tunnel:
                from app.tunnel.relay import record_tunnel_health

                # Feeds the automatic delegation breaker: repeated capture
                # failures here suspend delegation so the restore below (and
                # every future check) actually brings native WG back — no
                # one has to disable the tunnel by hand.
                record_tunnel_health(node_id, healthy=xray_exc is None)
            if xray_exc is not None:
                logger.warning(
                    "WireGuard node \"%s\" connected but Xray start failed (%s); "
                    "restoring native WireGuard",
                    dbnode.name,
                    xray_exc,
                )
                if not node.connected:
                    try:
                        node.connect()
                    except Exception:
                        pass
                node.wg_tunnel_capture_active = False
                with GetDB() as db:
                    from app.wireguard.operations import restore_relay_native_wireguard

                    # Re-fetch: ``dbnode`` above is detached (session already closed).
                    live = crud.get_node_by_id(db, node_id)
                    if live is not None:
                        restore_relay_native_wireguard(db, live, node_object=node)
                degraded_msg = _wg_xray_degraded_message(xray_exc)
            version = _wg_node_version_label(xray_failed=xray_exc is not None, xray_version=version)
        else:
            node.start(config)
            version = node.get_version()

        if not version:
            raise RuntimeError("Node did not report an Xray version")

        _change_node_status(node_id, NodeStatus.connected, message=degraded_msg, version=version)
        _persist_pinned_cert(node_id, getattr(node, "observed_cert_sha256", None))
        if degraded_msg:
            logger.info(
                "Connected to \"%s\" node (degraded: WG up, Xray down) — %s",
                dbnode.name,
                version,
            )
        else:
            logger.info(f"Connected to \"{dbnode.name}\" node, xray run on v{version}")

        _sync_wireguard_node(node_id, node)

        # Re-apply tunnels only when we actually re-pushed Xray (or stayed
        # degraded). Soft keep-live must not queue Apply — that restart storm
        # is what flaps healthy Reality hops.
        if (hard_reconnect and not kept_live) or degraded_msg:
            try:
                from app.jobs.tunnel_heal import schedule_reapply_for_node

                schedule_reapply_for_node(int(node_id), reason="node-hard-reconnect")
            except Exception:
                logger.debug(
                    "tunnel reapply schedule after connect failed for node %s",
                    node_id,
                    exc_info=True,
                )

    except Exception as e:
        _change_node_status(node_id, NodeStatus.error, message=str(e))
        logger.info(f"Unable to connect to \"{dbnode.name if dbnode else node_id}\" node")

    finally:
        _release_connecting_node(node_id)


@threaded_function
def restart_node(node_id, config=None):
    # Shares the connect_node() in-flight guard: the two operations both
    # touch xray.nodes[node_id] and talk to the same physical node, so they
    # must never run concurrently for the same id (H6/H7 — @threaded_function
    # fires a fresh, un-joined thread on every call; without this guard a
    # slow restart plus another health-check tick, manual "restart" click,
    # rule-engine action, or auto-upgrade job for the same node pile up
    # threads that all race node.restart()/node.disconnect()).
    if not _claim_connecting_node(node_id):
        return

    released = False
    dbnode = None
    try:
        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)

        if not dbnode:
            return

        try:
            node = xray.nodes[dbnode.id]
        except KeyError:
            node = _session_for_node(dbnode, reason="restart_node")

        if not node.connected:
            # connect_node() claims its own slot — release ours first so the
            # delegated call isn't immediately rejected by our own claim.
            _release_connecting_node(node_id)
            released = True
            return connect_node(node_id, config)
        # Existing live session on the public IP? Keep it for restart — moving
        # to a tunnel mid-restart is what hung TLS on some relays (SSH forward
        # accepts TCP, handshake never completes). Large-push failover still
        # uses ``_force_control_tunnel_session`` below on stream errors.
        if not getattr(node, "control_tunneled", False):
            pass
        elif not node.connected:
            moved = _force_control_tunnel_session(
                dbnode, node, reason="restart via tunnel"
            )
            if moved is not None:
                node = moved

        from app.models.node import CoreKind

        is_wg_node = dbnode.core_kind == CoreKind.wireguard.value

        logger.info(f"Restarting Xray core of \"{dbnode.name}\" node")

        if config is None:
            from app.services.xray_node import build_node_xray_config
            config = build_node_xray_config(node_id)
        else:
            from app.services.xray_node import filter_xray_config_for_node, node_xray_inbound_tags
            with GetDB() as db:
                allowed = node_xray_inbound_tags(db, node_id)
            config = filter_xray_config_for_node(config, allowed)
            config = _apply_node_tunnels(config, node_id)
            config = _apply_native_wireguard_inbound(config, node_id)
            config = _apply_node_warp_exit(config, node_id)

        if is_wg_node:
            with GetDB() as db:
                from app.tunnel.relay import (
                    node_delegates_wireguard_to_tunnel,
                    prepare_relay_wireguard_tunnel,
                )

                delegates_tunnel = node_delegates_wireguard_to_tunnel(db, node_id)
                prepare_relay_wireguard_tunnel(db, node_id, node)
            # Xray on a WireGuard node is best-effort (stats/API). Never drop
            # the RPyC channel when Xray restart fails — AWG/WG peers must stay up.
            if not node.connected:
                node.connect()
            xray_exc = None
            xray_version = None
            for attempt in range(3):
                try:
                    if not node.connected:
                        node.connect()
                    node.restart(config)
                    logger.info(f"Xray core of \"{dbnode.name}\" node restarted")
                    try:
                        xray_version = node.get_version()
                    except Exception:
                        pass
                    xray_exc = None
                    break
                except Exception as exc:
                    xray_exc = exc
                    logger.warning(
                        "WireGuard node \"%s\" Xray restart attempt %d failed (%s)",
                        dbnode.name,
                        attempt + 1,
                        exc,
                    )
                    if attempt < 2:
                        time.sleep(1)
                        try:
                            node.disconnect()
                        except Exception:
                            pass
                        if (
                            delegates_tunnel
                            and attempt == 0
                            and not getattr(node, "control_tunneled", False)
                        ):
                            # Same rationale as connect_node: a direct socket that
                            # connects fine but drops mid-write on a large tunnel
                            # config just retries into the same failure. Fail over
                            # to SSH for the retry instead.
                            forced = _force_control_tunnel_session(dbnode, node)
                            if forced is not None:
                                node = forced
            # ``config`` already reflects the desired inbound set for the
            # current delegation state (tunnel capture included/excluded via
            # _apply_node_tunnels/_apply_native_wireguard_inbound), so a
            # successful restart here means the live core now matches
            # ``delegates_tunnel`` — record that so a later connect_node
            # doesn't have to guess from liveness alone (see the
            # wg_tunnel_capture_active check there).
            node.wg_tunnel_capture_active = bool(delegates_tunnel and xray_exc is None)
            if delegates_tunnel:
                from app.tunnel.relay import record_tunnel_health

                record_tunnel_health(node_id, healthy=xray_exc is None)
            if xray_exc is not None:
                logger.warning(
                    "WireGuard node \"%s\" Xray restart failed (%s); restoring native WireGuard",
                    dbnode.name,
                    xray_exc,
                )
                if not node.connected:
                    try:
                        node.connect()
                    except Exception:
                        pass
                with GetDB() as db:
                    from app.wireguard.operations import restore_relay_native_wireguard

                    # Re-fetch: ``dbnode`` above is detached (session already closed).
                    live = crud.get_node_by_id(db, node_id)
                    if live is not None:
                        restore_relay_native_wireguard(db, live, node_object=node)
            _sync_wireguard_node(node_id, node)
            if node.connected:
                _mark_wg_node_connected(
                    node_id,
                    node,
                    xray_exc=xray_exc,
                    xray_version=xray_version,
                )
            return

        node.restart(config)
        logger.info(f"Xray core of \"{dbnode.name}\" node restarted")
    except Exception as e:
        _change_node_status(node_id, NodeStatus.error, message=str(e))
        logger.info(f"Unable to restart node {node_id}")
        try:
            xray.nodes[node_id].disconnect()
        except Exception:
            pass
    finally:
        if not released:
            _release_connecting_node(node_id)


__all__ = [
    "add_user",
    "sync_core_users",
    "sync_core_users_async",
    "schedule_core_sync",
    "sync_core_users_now",
    "remove_user",
    "remove_user_immediate",
    "hot_disconnect_users_on_nodes",
    "add_node",
    "remove_node",
    "connect_node",
    "restart_node",
]
