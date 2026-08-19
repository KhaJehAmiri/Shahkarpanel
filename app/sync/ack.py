"""Live read-back ACK after a single-user hot apply (Phase 3).

ACK means the running HandlerService (or Finalmask adi) confirmed the
email/peer is present or gone. Memory registry, last_config, and shard
fingerprints are not ACK.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import xray
from app.db import GetDB, crud

logger = logging.getLogger("uvicorn.error")

_ACK_TIMEOUT = 3.0


class AckError(RuntimeError):
    """Live core did not confirm the expected membership."""


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
        from app.db.proxy_dedupe import get_user_proxy
        from app.models.proxy import ProxyTypes
        from app.wireguard.finalmask_shard import user_finalmask_slot

        with GetDB() as db:
            proxy = get_user_proxy(db, int(dbuser.id), ProxyTypes.WireGuard)
            if proxy is None:
                return None
            return user_finalmask_slot(dict(proxy.settings or {}))
    except Exception:
        return None


def _main_api_live() -> bool:
    if not getattr(xray.core, "started", False) or getattr(xray.core, "restarting", False):
        return False
    try:
        xray.api.get_sys_stats(timeout=2)
        return True
    except Exception:
        return False


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
        out.append((int(node_id), api))
    return out


def _node_allowlists() -> dict[int, Optional[set]]:
    from app.services.xray_node import node_xray_inbound_tags

    ids = [nid for nid, _api in _live_nodes()]
    if not ids:
        return {}
    with GetDB() as db:
        return {nid: node_xray_inbound_tags(db, nid) for nid in ids}


def email_present(api, tag: str, account) -> Optional[bool]:
    """True when the live inbound has this email. None = tag not on this core."""
    try:
        api.add_inbound_user(tag=tag, user=account, timeout=_ACK_TIMEOUT)
        return True
    except xray.exc.EmailExistsError:
        return True
    except xray.exc.TagNotFoundError:
        return None
    except (xray.exc.ConnectionError, xray.exc.TimeoutError) as exc:
        raise AckError(f"xray present probe failed tag={tag}: {exc}") from exc


def email_absent(api, tag: str, email: str) -> bool:
    """True when the live inbound does not have this email."""
    try:
        api.remove_inbound_user(tag=tag, email=email, timeout=_ACK_TIMEOUT)
        return True
    except xray.exc.EmailNotFoundError:
        return True
    except xray.exc.TagNotFoundError:
        return True
    except (xray.exc.ConnectionError, xray.exc.TimeoutError) as exc:
        raise AckError(f"xray absent probe failed tag={tag}: {exc}") from exc


def _confirm_present(accounts: list) -> None:
    """ACK the panel's own core. Node AlterInbound is best-effort in apply."""
    if not accounts:
        return
    if not _main_api_live():
        logger.warning("present ACK skipped — main core not live")
        return
    failures: list[str] = []
    for tag, account in accounts:
        if tag not in xray.config.inbounds_by_tag:
            continue
        try:
            got = email_present(xray.api, tag, account)
        except AckError as exc:
            failures.append(str(exc))
            continue
        if got is False:
            failures.append(f"main:{tag}")
    if failures:
        raise AckError("present ACK failed: " + "; ".join(failures[:12]))


def _confirm_absent(email: str, tags: list[str]) -> None:
    """ACK the panel's own core. Node removes are best-effort in apply."""
    if not email or not tags:
        return
    if not _main_api_live():
        logger.warning("absent ACK skipped — main core not live")
        return
    failures: list[str] = []
    for tag in tags:
        try:
            if not email_absent(xray.api, tag, email):
                failures.append(f"main:{tag}")
        except AckError as exc:
            failures.append(str(exc))
    if failures:
        raise AckError("absent ACK failed: " + "; ".join(failures[:12]))


def _confirm_finalmask_slot(slot: Optional[int], *, want_peer: bool) -> None:
    """adi already ran during apply; require the shard inbound to still answer."""
    if slot is None:
        return
    from app.wireguard.finalmask_shard import shard_inbound_tag
    from app.wireguard.xray_native import xray_native_wg_enabled

    with GetDB() as db:
        nodes = [
            n
            for n in crud.get_wireguard_nodes(db)
            if n.wireguard is not None and xray_native_wg_enabled(n.wireguard)
        ]
        node_ids = [int(n.id) for n in nodes]
    if not node_ids:
        return
    live = {nid: api for nid, api in _live_nodes()}
    missing_live = [nid for nid in node_ids if nid not in live]
    # Connecting/error nodes are Phase 4 drift, not a user-ACK failure.
    failures: list[str] = []
    for nid, api in live.items():
        if nid not in node_ids:
            continue
        tag = shard_inbound_tag(nid, int(slot))
        try:
            api.get_sys_stats(timeout=2)
        except Exception as exc:
            failures.append(f"finalmask node{nid} sys_stats: {exc}")
            continue
        # Inbound stats exist for a live tag (zeros are fine). A dead tag
        # still returns zeros, so this is liveness of the node API after adi.
        try:
            api.get_inbound_stats(tag, reset=False, timeout=2)
        except Exception as exc:
            failures.append(f"finalmask node{nid} {tag}: {exc}")
        _ = want_peer  # peer membership was the adi payload; CLI ok is apply ACK
    if failures:
        logger.warning(
            "finalmask ACK incomplete slot=%s: %s",
            slot,
            "; ".join(failures[:8]),
        )
    if missing_live:
        logger.info(
            "finalmask ACK skipped disconnected nodes %s slot=%s",
            missing_live,
            slot,
        )


def confirm_action(action: str, *, user_id=None, payload: Optional[dict] = None) -> None:
    """Raise AckError unless live cores match the outbox action."""
    payload = dict(payload or {})
    action = (action or "").strip()

    if action == "delete":
        email = _email(payload=payload)
        from app.xray.serving import _inbound_supports_hot_sync

        tags = [t for t in xray.config.inbounds_by_tag if _inbound_supports_hot_sync(t)]
        _confirm_absent(email, tags)
        _confirm_finalmask_slot(_slot(payload=payload), want_peer=False)
        return

    with GetDB() as db:
        dbuser = crud.get_user_by_id(db, int(user_id)) if user_id else None
        if dbuser is None:
            if action in ("disable", "delete"):
                confirm_action("delete", payload=payload)
                return
            if action in ("add", "protocol_change", "quota_cap"):
                return
            raise AckError(f"ack user {user_id} missing")
        from app.xray.serving import iter_user_hot_accounts, _inbound_supports_hot_sync

        accounts = list(iter_user_hot_accounts(dbuser))
        email = _email(dbuser, payload)
        slot = _slot(dbuser, payload)
        hot_tags = [t for t in xray.config.inbounds_by_tag if _inbound_supports_hot_sync(t)]

    if action in ("add", "protocol_change", "quota_cap"):
        _confirm_present(accounts)
        _confirm_finalmask_slot(slot, want_peer=True)
        return

    if action == "disable":
        _confirm_absent(email, hot_tags)
        _confirm_finalmask_slot(slot, want_peer=False)
        return

    raise AckError(f"unhandled ack action {action}")
