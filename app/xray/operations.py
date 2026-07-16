import threading
import time
from functools import lru_cache
from typing import TYPE_CHECKING

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
        from app.wireguard.operations import sync_node
        from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if not dbnode or dbnode.wireguard is None:
                pass
            else:
                cfg = dbnode.wireguard
                if plain_wg_enabled(cfg) or amneziawg_enabled(cfg):
                    ok = sync_node(db, dbnode, node_object=node_object)
                    if not ok:
                        logger.warning("WireGuard sync to node %s did not apply (client unavailable or no specs)", node_id)
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


def _apply_native_wireguard_inbound(config, node_id: int):
    """Fold this WG node's Xray-native WireGuard+noise inbound into its config.

    Best-effort and independent of the tunnel injection above: this is a
    self-contained inbound (terminates locally, dispatches to ``DIRECT`` or
    WARP when enabled), not a relay/transit/exit tunnel fragment.

    Always replaces an existing ``node-{id}-xray-wg-in`` entry so peer IP
    expansions (thousands of users) are reflected on the next Xray restart —
    appending only when the tag is missing would leave a stale peer set.
    """
    try:
        from app.db import GetDB, crud
        from app.wireguard.operations import (
            collect_wg_peers,
            ensure_plain_addresses_for_finalmask,
        )
        from app.wireguard.xray_native import (
            build_xray_wireguard_inbound,
            xray_native_wg_enabled,
        )

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            cfg = dbnode.wireguard if dbnode else None
            if not xray_native_wg_enabled(cfg):
                return config

            ensure_plain_addresses_for_finalmask(db)
            peers = collect_wg_peers(db)
            outbound_tag = "DIRECT"
            if dbnode and bool(getattr(dbnode, "warp_enabled", False)):
                outbound_tag = (getattr(dbnode, "warp_tag", None) or "warp").strip() or "warp"
            inbound, rule = build_xray_wireguard_inbound(
                cfg, peers, node_id=node_id, outbound_tag=outbound_tag,
            )
        if inbound is None:
            return config

        result = config.copy()
        inbounds = list(result.get("inbounds") or [])
        tag = inbound["tag"]
        inbounds = [ib for ib in inbounds if not (isinstance(ib, dict) and ib.get("tag") == tag)]
        inbounds.append(inbound)
        result["inbounds"] = inbounds

        routing = result.setdefault("routing", {})
        rules = list(routing.get("rules") or [])
        rules = [
            r for r in rules
            if not (
                isinstance(r, dict)
                and tag in (r.get("inboundTag") or [])
            )
        ]
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
        pinned_cert_sha256=getattr(dbnode, "server_cert_sha256", None),
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
    xray.nodes[dbnode.id] = node

    return xray.nodes[dbnode.id]


def _ssh_host_for_node(dbnode) -> str:
    return (getattr(dbnode, "provision_host", None) or dbnode.address or "").strip()


def _connect_node_session(dbnode, node):
    """Connect ``node``, falling back to an SSH control tunnel when needed."""
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


def _force_control_tunnel_session(dbnode, node):
    """Rebuild the node session over the SSH control tunnel.

    Fallback for routes where the direct TLS/RPyC socket connects fine (so
    ``node.connect()`` never raises) but drops mid-write on a large payload —
    seen on some Iran↔abroad paths as ``EOFError: stream has been closed``
    while pushing a big WireGuard/Finalmask config. Plain reconnect-and-retry
    on the same direct path reproduces the same failure every time; routing
    the bulk transfer through SSH (which handles its own retransmission)
    is what actually gets a large config through automatically.
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
        "Node %s: switched to SSH control tunnel after a direct large-config "
        "transfer failure",
        dbnode.id,
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
                node = add_node(dbnode)

            if not node.connected:
                node.connect()

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
                    if not node.connected:
                        node.connect()
            else:
                node.restart(config)

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

        try:
            node = xray.nodes[dbnode.id]
            if not node.connected:
                raise KeyError
        except KeyError:
            preferred = _prefer_control_tunnel(dbnode)
            node = preferred if preferred is not None else xray.operations.add_node(dbnode)

        _change_node_status(node_id, NodeStatus.connecting)

        need_connect = True
        if node.connected:
            try:
                node.get_version()
                need_connect = False
            except Exception:
                pass
        if need_connect:
            logger.info(f"Connecting to \"{dbnode.name}\" node")
            try:
                node = _connect_node_session(dbnode, node)
            except Exception:
                node = xray.operations.add_node(dbnode)
                node = _connect_node_session(dbnode, node)
        else:
            logger.debug("Reusing live RPyC session for \"%s\"", dbnode.name)

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

        from app.models.node import CoreKind

        is_wg_node = dbnode.core_kind == CoreKind.wireguard.value
        version = None
        degraded_msg = None
        if is_wg_node:
            with GetDB() as db:
                from app.tunnel.relay import (
                    node_delegates_wireguard_to_tunnel,
                    prepare_relay_wireguard_tunnel,
                )

                delegates_tunnel = node_delegates_wireguard_to_tunnel(db, node_id)
            if delegates_tunnel:
                # Do not early-return on get_version alone: the agent can still
                # report a version while UDP capture (51820/51901) is down, which
                # left clients timing out. Always fall through to start/restart
                # (with prepare_relay freeing the plain WG port first).
                try:
                    if not node.connected:
                        node.connect()
                    with GetDB() as db:
                        prepare_relay_wireguard_tunnel(db, node_id, node)
                except Exception:
                    pass
            # WireGuard nodes need the RPyC channel for wg_apply; Xray on the
            # node is best-effort (stats/API) and must not block AWG sync.
            xray_exc = None
            version = None
            if delegates_tunnel:
                # Prefer reuse when the agent already has a live core. Blind
                # restart of a ~2MB Finalmask config OOMs small relay VMs
                # (second Xray during stop/start) and leaves UDP dead.
                for attempt in range(3):
                    try:
                        if not node.connected:
                            node.connect()
                        with GetDB() as db:
                            prepare_relay_wireguard_tunnel(db, node_id, node)
                        try:
                            version = node.get_version()
                            # get_version alone only proves *some* Xray core is
                            # alive — the live one could be a stale native-
                            # fallback push from before delegation was granted
                            # (or regranted after a breaker suspension). Only
                            # skip the restart when we know the live core is
                            # the one that actually captured the tunnel port.
                            if (
                                version
                                and getattr(node, "started", False)
                                and getattr(node, "wg_tunnel_capture_active", False)
                            ):
                                xray_exc = None
                                logger.info(
                                    "WireGuard node \"%s\" keeping live Xray (%s)",
                                    dbnode.name,
                                    version,
                                )
                                break
                        except Exception:
                            version = None
                        try:
                            node.start(config)
                        except Exception:
                            node.restart(config)
                        version = node.get_version()
                        node.wg_tunnel_capture_active = True
                        xray_exc = None
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
                for attempt in range(3):
                    try:
                        if not node.connected:
                            node.connect()
                        node.start(config)
                        version = node.get_version()
                        node.wg_tunnel_capture_active = False
                        xray_exc = None
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

                    restore_relay_native_wireguard(db, dbnode, node_object=node)
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
            node = xray.operations.add_node(dbnode)

        if not node.connected:
            # connect_node() claims its own slot — release ours first so the
            # delegated call isn't immediately rejected by our own claim.
            _release_connecting_node(node_id)
            released = True
            return connect_node(node_id, config)

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

                    restore_relay_native_wireguard(db, dbnode, node_object=node)
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
