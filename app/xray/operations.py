from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from app import logger, xray
from app.db import GetDB, crud
from app.models.node import NodeStatus
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
    try:
        api.add_inbound_user(tag=inbound_tag, user=account, timeout=30)
    except (xray.exc.EmailExistsError, xray.exc.ConnectionError):
        pass


@threaded_function
def _remove_user_from_inbound(api: XRayAPI, inbound_tag: str, email: str):
    try:
        api.remove_inbound_user(tag=inbound_tag, email=email, timeout=30)
    except (xray.exc.EmailNotFoundError, xray.exc.ConnectionError):
        pass


@threaded_function
def _alter_inbound_user(api: XRayAPI, inbound_tag: str, account: Account):
    try:
        api.remove_inbound_user(tag=inbound_tag, email=account.email, timeout=30)
    except (xray.exc.EmailNotFoundError, xray.exc.ConnectionError):
        pass
    try:
        api.add_inbound_user(tag=inbound_tag, user=account, timeout=30)
    except (xray.exc.EmailExistsError, xray.exc.ConnectionError):
        pass


def sync_core_users():
    sync_core_users_now()


@threaded_function
def sync_core_users_async():
    schedule_core_sync()


def _sync_wireguard():
    """Best-effort: converge native WireGuard nodes after a user change."""
    try:
        from app.wireguard.operations import sync_user_change
        sync_user_change()
    except Exception:
        pass
    try:
        from app.singbox.operations import sync_user_change as singbox_sync
        singbox_sync()
    except Exception:
        pass


def _sync_wireguard_node(node_id: int, node_object):
    """Best-effort: push the current peer set to a node that just connected."""
    try:
        from app.models.node import CoreKind
        from app.wireguard.operations import sync_node

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode and dbnode.core_kind == CoreKind.wireguard.value:
                sync_node(db, dbnode, node_object=node_object)
    except Exception:
        pass
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
        api.remove_inbound_user(tag=inbound_tag, email=email, timeout=30)
    except (xray.exc.EmailNotFoundError, xray.exc.ConnectionError):
        pass


def remove_user_immediate(dbuser: "DBUser"):
    """Stop serving immediately — rebuild core from DB (excludes non-active users)."""
    sync_core_users_now()


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
            if getattr(account, 'flow', None) and (
                inbound.get('network', 'tcp') not in ('tcp', 'kcp')
                or (
                    inbound.get('network', 'tcp') in ('tcp', 'kcp')
                    and inbound.get('tls') not in ('tls', 'reality')
                )
                or inbound.get('header_type') == 'http'
            ):
                account.flow = XTLSFlows.NONE
            for node in list(xray.nodes.values()):
                if node.connected and node.started:
                    _alter_inbound_user(node.api, inbound_tag, account)


def update_user(dbuser: "DBUser"):
    schedule_core_sync()
    sync_main_core_user(dbuser)
    _push_user_to_nodes(dbuser)


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


def add_node(dbnode: "DBNode"):
    remove_node(dbnode.id)

    tls = get_tls()
    xray.nodes[dbnode.id] = XRayNode(address=dbnode.address,
                                     port=dbnode.port,
                                     api_port=dbnode.api_port,
                                     ssl_key=tls['key'],
                                     ssl_cert=tls['certificate'],
                                     usage_coefficient=dbnode.usage_coefficient)

    return xray.nodes[dbnode.id]


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


global _connecting_nodes
_connecting_nodes = {}


@threaded_function
def connect_node(node_id, config=None):
    global _connecting_nodes

    if _connecting_nodes.get(node_id):
        return

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)

    if not dbnode:
        return

    try:
        node = xray.nodes[dbnode.id]
        assert node.connected
    except (KeyError, AssertionError):
        node = xray.operations.add_node(dbnode)

    try:
        _connecting_nodes[node_id] = True

        _change_node_status(node_id, NodeStatus.connecting)
        logger.info(f"Connecting to \"{dbnode.name}\" node")

        if config is None:
            config = xray.config.include_db_users()
        config = _apply_node_tunnels(config, node_id)

        node.start(config)
        version = node.get_version()
        _change_node_status(node_id, NodeStatus.connected, version=version)
        logger.info(f"Connected to \"{dbnode.name}\" node, xray run on v{version}")

        _sync_wireguard_node(node_id, node)

    except Exception as e:
        _change_node_status(node_id, NodeStatus.error, message=str(e))
        logger.info(f"Unable to connect to \"{dbnode.name}\" node")

    finally:
        try:
            del _connecting_nodes[node_id]
        except KeyError:
            pass


@threaded_function
def restart_node(node_id, config=None):
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)

    if not dbnode:
        return

    try:
        node = xray.nodes[dbnode.id]
    except KeyError:
        node = xray.operations.add_node(dbnode)

    if not node.connected:
        return connect_node(node_id, config)

    try:
        logger.info(f"Restarting Xray core of \"{dbnode.name}\" node")

        if config is None:
            config = xray.config.include_db_users()
        config = _apply_node_tunnels(config, node_id)

        node.restart(config)
        logger.info(f"Xray core of \"{dbnode.name}\" node restarted")
    except Exception as e:
        _change_node_status(node_id, NodeStatus.error, message=str(e))
        logger.info(f"Unable to restart node {node_id}")
        try:
            node.disconnect()
        except Exception:
            pass


__all__ = [
    "add_user",
    "sync_core_users",
    "sync_core_users_async",
    "schedule_core_sync",
    "sync_core_users_now",
    "remove_user",
    "remove_user_immediate",
    "add_node",
    "remove_node",
    "connect_node",
    "restart_node",
]
