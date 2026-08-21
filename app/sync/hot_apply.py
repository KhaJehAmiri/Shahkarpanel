"""Single-user live apply (Phase 3). Worker-only; HTTP never calls this.

Adds/removes one email or one Finalmask slot on the running cores. Never
rebuilds ``include_db_users()`` and never restarts a node for one account.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from app import xray
from app.db import GetDB, crud

logger = logging.getLogger("uvicorn.error")

_ACK_TIMEOUT = 1.2


def _email(dbuser=None, payload: Optional[dict] = None) -> str:
    if dbuser is not None:
        return f"{dbuser.id}.{dbuser.username}"
    payload = payload or {}
    return str(payload.get("email") or "")


def _slot(dbuser=None, payload: Optional[dict] = None) -> Optional[int]:
    payload = payload or {}
    if payload.get("slot") is not None:
        try:
            return int(payload["slot"])
        except (TypeError, ValueError):
            pass
    if dbuser is None:
        return None
    try:
        from app.wireguard.finalmask_shard import user_finalmask_slot
        from app.db.proxy_dedupe import get_user_proxy
        from app.models.proxy import ProxyTypes

        with GetDB() as db:
            proxy = get_user_proxy(db, int(dbuser.id), ProxyTypes.WireGuard)
            if proxy is None:
                return None
            return user_finalmask_slot(dict(proxy.settings or {}))
    except Exception:
        return None


def _node_allowlists() -> dict[int, Optional[set]]:
    from app.services.xray_node import node_xray_inbound_tags

    ids = [int(nid) for nid in list(xray.nodes)]
    if not ids:
        return {}
    with GetDB() as db:
        return {nid: node_xray_inbound_tags(db, nid) for nid in ids}


def _live_nodes():
    out = []
    for node_id, node in list(xray.nodes.items()):
        live = (
            (getattr(node, "has_live_api", None) and node.has_live_api())
            or (
                getattr(node, "started", False)
                and getattr(node, "_api", None) is not None
            )
        )
        if not live:
            continue
        try:
            api = node.api
        except Exception:
            continue
        out.append((int(node_id), node, api))
    return out


def _main_api_live() -> bool:
    if not getattr(xray.core, "started", False) or getattr(xray.core, "restarting", False):
        return False
    try:
        xray.api.get_sys_stats(timeout=2)
        return True
    except Exception:
        return False


def _alter_add(api, tag: str, account) -> None:
    api.add_inbound_user(tag=tag, user=account, timeout=_ACK_TIMEOUT)


def _alter_remove(api, tag: str, email: str) -> None:
    api.remove_inbound_user(tag=tag, email=email, timeout=_ACK_TIMEOUT)


def _push_accounts_to_nodes(accounts: list) -> None:
    """Synchronous AlterInbound add for one user's hot-capable tags."""
    allow = _node_allowlists()
    for node_id, _node, api in _live_nodes():
        allowed = allow.get(node_id)
        timed_out = False
        for tag, account in accounts:
            if timed_out:
                break
            if allowed is not None and tag not in allowed:
                continue
            try:
                _alter_add(api, tag, account)
            except (xray.exc.EmailExistsError, xray.exc.TagNotFoundError):
                pass
            except (xray.exc.ConnectionError, xray.exc.TimeoutError):
                logger.warning("hot-add node=%s tag=%s timeout/conn", node_id, tag)
                timed_out = True
            except Exception:
                logger.debug("hot-add node=%s tag=%s failed", node_id, tag, exc_info=True)


def _remove_email_from_nodes(email: str, tags: list[str]) -> None:
    allow = _node_allowlists()
    for node_id, _node, api in _live_nodes():
        allowed = allow.get(node_id)
        timed_out = False
        for tag in tags:
            if timed_out:
                break
            if allowed is not None and tag not in allowed:
                continue
            try:
                _alter_remove(api, tag, email)
            except (xray.exc.EmailNotFoundError, xray.exc.TagNotFoundError):
                pass
            except (xray.exc.ConnectionError, xray.exc.TimeoutError):
                timed_out = True
            except Exception:
                logger.debug("hot-remove node=%s tag=%s failed", node_id, tag, exc_info=True)


def _flush_slot(slot: Optional[int]) -> bool:
    if slot is None:
        return True
    from app.wireguard.finalmask_reload import (
        mark_finalmask_slots_dirty,
        schedule_finalmask_xray_reload,
    )

    mark_finalmask_slots_dirty([int(slot)])
    # Never flush inline while the outbox drain lock is held. A sync
    # hot-replace of every dirty shard is what made bulk-create Finalmask
    # land minutes late (DeadlineExceeded → 20s retry). Coalesce instead.
    schedule_finalmask_xray_reload(delay=0.2, bulk=True)
    return True


def _user_has_singbox(dbuser) -> bool:
    from app.models.proxy import ProxyTypes

    wanted = {ProxyTypes.Hysteria2, ProxyTypes.TUIC, ProxyTypes.AnyTLS, "Hysteria2", "TUIC", "AnyTLS"}
    for proxy in getattr(dbuser, "proxies", None) or []:
        if getattr(proxy, "type", None) in wanted:
            return True
    return False


def apply_action(action: str, *, user_id=None, payload: Optional[dict] = None) -> None:
    """Mutate live cores for one outbox row. Raises on hard apply failure."""
    payload = dict(payload or {})
    action = (action or "").strip()

    if action == "delete":
        apply_delete(payload)
        return

    from app.xray.serving import hot_disconnect_users, iter_user_hot_accounts, sync_main_core_user

    with GetDB() as db:
        dbuser = crud.get_user_by_id(db, int(user_id)) if user_id else None
        if dbuser is None:
            if action in ("disable", "delete"):
                apply_delete(payload)
                return
            if action in ("add", "protocol_change", "quota_cap"):
                logger.info("hot-apply skip %s — user %s already gone", action, user_id)
                return
            raise RuntimeError(f"hot-apply user {user_id} missing for action={action}")
        # Materialize while the session is open.
        accounts = list(iter_user_hot_accounts(dbuser))
        slot = _slot(dbuser, payload)
        has_sb = _user_has_singbox(dbuser)
        uid = int(dbuser.id)

    if action in ("add", "protocol_change"):
        try:
            from app.wireguard.instant_sync import provision_and_sync_wireguard_user

            provision_and_sync_wireguard_user(uid, push=False)
        except Exception:
            logger.debug("hot-apply WG provision skipped", exc_info=True)
        with GetDB() as db:
            dbuser = crud.get_user_by_id(db, uid)
            if dbuser is None:
                raise RuntimeError(f"hot-apply user {uid} vanished")
            sync_main_core_user(dbuser)
            accounts = list(iter_user_hot_accounts(dbuser))
            slot = _slot(dbuser, payload)
            has_sb = _user_has_singbox(dbuser)
            from app.singbox.operations import user_identifiers

            sb_names = user_identifiers(dbuser, payload)

        def _bg_nodes():
            _push_accounts_to_nodes(accounts)
            if has_sb:
                try:
                    from app.singbox.operations import sync_user_change, unrevoke_singbox_users

                    unrevoke_singbox_users(sb_names)
                    sync_user_change()
                except Exception:
                    logger.debug("hot-apply singbox bg failed", exc_info=True)

        threading.Thread(target=_bg_nodes, name=f"hot-add-{uid}", daemon=True).start()
        _flush_slot(slot)
        return

    if action == "disable":
        with GetDB() as db:
            dbuser = crud.get_user_by_id(db, uid)
            if dbuser is None:
                apply_delete(payload)
                return
            hot_disconnect_users([dbuser])
            email = _email(dbuser, payload)
            slot = _slot(dbuser, payload)
            from app.singbox.operations import user_identifiers

            sb_names = user_identifiers(dbuser, payload)
        from app.xray.serving import _inbound_supports_hot_sync

        tags = [
            tag
            for tag in xray.config.inbounds_by_tag
            if _inbound_supports_hot_sync(tag)
        ]
        if email:
            threading.Thread(
                target=_remove_email_from_nodes,
                args=(email, tags),
                name=f"hot-dis-{uid}",
                daemon=True,
            ).start()
        if sb_names:
            try:
                from app.singbox.operations import revoke_singbox_users

                revoke_singbox_users(sb_names)
            except Exception:
                logger.debug("hot-apply singbox revoke failed", exc_info=True)
        _flush_slot(slot)
        return

    if action == "quota_cap":
        from app.models.user import UserStatus
        from app.xray.serving import sync_main_core_user

        with GetDB() as db:
            dbuser = crud.get_user_by_id(db, uid)
            if dbuser is None:
                return
            if dbuser.status in (UserStatus.active, UserStatus.on_hold):
                sync_main_core_user(dbuser)
        return

    raise RuntimeError(f"unhandled hot-apply action {action}")


def apply_delete(payload: dict) -> None:
    email = _email(payload=payload)
    slot = _slot(payload=payload)
    tags = list(xray.config.inbounds_by_tag.keys())
    if email:
        from app.xray.serving import _api_remove_user, _inbound_supports_hot_sync

        if _main_api_live():
            for tag in tags:
                if not _inbound_supports_hot_sync(tag):
                    continue
                _api_remove_user(tag, email)
        threading.Thread(
            target=_remove_email_from_nodes,
            args=(email, tags),
            name="hot-del-nodes",
            daemon=True,
        ).start()
    _flush_slot(slot)
    def _bg_proto():
        try:
            from app.wireguard.operations import sync_user_change
            from app.singbox.operations import revoke_singbox_users, user_identifiers

            sync_user_change(immediate=True)
            revoke_singbox_users(user_identifiers(payload=payload))
        except Exception:
            logger.debug("hot-apply delete protocol sync failed", exc_info=True)

    threading.Thread(target=_bg_proto, name="hot-del-proto", daemon=True).start()
