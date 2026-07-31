"""Keep the live Xray core aligned with billable users in the database.

* The main core is mutated **in place** via the handler gRPC API (add/remove
  inbound user) so existing sessions of unrelated users are never dropped.
* We keep an authoritative in-memory **registry** of which ``email`` we have
  pushed into each inbound. Xray's API cannot list configured users, and
  ``get_users_stats`` is unreliable (the usage job resets counters every few
  seconds), so a diff against live stats would be wrong. The registry is the
  source of truth for "what the core currently has".
* The registry is rebuilt from ``xray.core.last_config`` whenever the core is
  (re)started — detected through ``xray.core.config_generation`` — so it can
  never drift away from a fresh ``include_db_users()`` restart.
* A periodic reconcile re-applies the DB → core diff so an active user can
  never stay missing after a transient hiccup.
* A full config rebuild + restart is the fallback only when the core is down
  or its API is unreachable.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from app import xray
from app.db import GetDB, crud
from app.models.proxy import ProxySettings, ProxyTypes
from app.models.user import UserStatus
from xray_api.types.account import XTLSFlows

if TYPE_CHECKING:
    from xray_api.types.account import Account

logger = logging.getLogger("shahkar-xray-serving")

_sync_lock = threading.Lock()
_sync_timer: threading.Timer | None = None
_DEBOUNCE_SEC = 1.5
_POST_START_GRACE_SEC = 15.0
_FULL_RESTART_MIN_INTERVAL_SEC = 45.0
_last_full_restart_at: float = 0.0

# Authoritative view of what we have pushed into the live core.
#   inbound_tag -> set(email)
_hot_lock = threading.RLock()
_registered: dict[str, set[str]] = {}
_registry_generation = -1


def _sync_wireguard():
    try:
        from app.wireguard.operations import sync_user_change
        sync_user_change()
    except Exception:
        logger.exception("WireGuard sync failed")
    try:
        from app.singbox.operations import sync_user_change as singbox_sync
        singbox_sync()
    except Exception:
        logger.exception("sing-box sync failed")


def _inbound_supports_hot_sync(inbound_tag: str) -> bool:
    """SS-2022 users are config-reload only; gRPC AddUser panics the core."""
    inbound = xray.config.inbounds_by_tag.get(inbound_tag)
    if not inbound and xray.core.last_config is not None:
        inbound = xray.core.last_config.get_inbound(inbound_tag) or {}
    if not inbound:
        return False
    if inbound.get("protocol") != "shadowsocks":
        return True
    from xray_api.types.account import is_ss2022

    method = inbound.get("ss_method") or (inbound.get("settings") or {}).get("method") or ""
    return not is_ss2022(method)


def _proxy_settings_map(dbuser) -> dict["ProxyTypes", "ProxySettings"]:
    """Build ``{ProxyTypes: ProxySettings}`` straight from the ORM row.

    Deliberately avoids ``UserResponse.model_validate()`` here: that model's
    ``validate_subscription_url``/``validate_links`` validators always run
    and resolve the user's full subscription link (a DB query per user via
    ``list_subscription_token_aliases_for_user``). This hot path only needs
    proxy credentials to push into Xray — with thousands of users, paying
    for a subscription-link DB round trip per user on every hot-sync/reconcile
    tick was the dominant cost keeping the panel busy well past its interval.
    """
    result: dict[ProxyTypes, ProxySettings] = {}
    for proxy in dbuser.proxies:
        ptype = proxy.type if isinstance(proxy.type, ProxyTypes) else ProxyTypes(proxy.type)
        result[ptype] = ProxySettings.from_dict(ptype, proxy.settings)
    return result


def _account_for_inbound(
    proxies: dict, proxy_type, inbound_tag: str, email: str,
    *, user_id: int, speed_limit_up: int | None, speed_limit_down: int | None,
) -> "Account | None":
    inbound = xray.config.inbounds_by_tag.get(inbound_tag, {})
    try:
        proxy_settings = proxies[proxy_type].dict(no_obj=True)
    except KeyError:
        return None
    account = proxy_type.account_model(email=email, **proxy_settings)
    if speed_limit_up or speed_limit_down:
        account.level = (user_id % 9000) + 100
    if proxy_type == ProxyTypes.VLESS:
        from app.xray.network_defaults import effective_vless_flow

        flow_val = effective_vless_flow(
            getattr(account.flow, "value", None) if getattr(account, "flow", None) else None,
            inbound,
        )
        account.flow = XTLSFlows(flow_val) if flow_val else XTLSFlows.NONE
    elif proxy_type == ProxyTypes.Trojan:
        account.flow = XTLSFlows.NONE
    if getattr(account, "flow", None) and (
        inbound.get("network", "tcp") not in ("tcp", "kcp", "raw")
        or (
            inbound.get("network", "tcp") in ("tcp", "kcp", "raw")
            and inbound.get("tls") not in ("tls", "reality")
        )
        or inbound.get("header_type") == "http"
    ):
        account.flow = XTLSFlows.NONE
    return account


def _build_desired_by_inbound() -> dict[str, dict[str, "Account"]]:
    """Map inbound tag -> {email -> Account} for every billable user.

    Validation/proxy access happens while the DB session is still open;
    SQLAlchemy lazy-loads (``proxies``/``inbounds``) cannot survive a detached
    instance, so we must materialize the accounts inside the ``with`` block.

    Note: ``get_user_queryset`` uses ``joinedload`` on collections, which is
    incompatible with ``yield_per`` (SQLAlchemy InvalidRequestError). Chunk by
    primary key instead so hot-sync keeps working for new reseller accounts.
    """
    from sqlalchemy.orm import selectinload

    from app.db.models import Proxy, User

    desired: dict[str, dict[str, Account]] = defaultdict(dict)

    with GetDB() as db:
        last_id = 0
        while True:
            batch = (
                db.query(User)
                .options(
                    selectinload(User.proxies).selectinload(Proxy.excluded_inbounds),
                )
                .filter(
                    User.status.in_([UserStatus.active, UserStatus.on_hold]),
                    User.id > last_id,
                )
                .order_by(User.id)
                .limit(500)
                .all()
            )
            if not batch:
                break
            for dbuser in batch:
                proxies = _proxy_settings_map(dbuser)
                email = f"{dbuser.id}.{dbuser.username}"
                for proxy_type, inbound_tags in dbuser.inbounds.items():
                    from app.utils.device_exclusivity import is_xray_proxy_held

                    pt = proxy_type.value if hasattr(proxy_type, "value") else str(proxy_type)
                    if is_xray_proxy_held(dbuser, pt):
                        continue
                    for inbound_tag in inbound_tags:
                        account = _account_for_inbound(
                            proxies, proxy_type, inbound_tag, email,
                            user_id=dbuser.id,
                            speed_limit_up=dbuser.speed_limit_up,
                            speed_limit_down=dbuser.speed_limit_down,
                        )
                        if account is not None:
                            desired[inbound_tag][email] = account
            last_id = batch[-1].id
    return desired


def _reset_registry_from_config(config) -> None:
    """Seed the registry with the users a freshly (re)started core booted with."""
    with _hot_lock:
        _registered.clear()
        for inbound in config.get("inbounds", []):
            tag = inbound.get("tag")
            clients = (inbound.get("settings") or {}).get("clients") or []
            emails = {c.get("email") for c in clients if isinstance(c, dict) and c.get("email")}
            if emails:
                _registered[tag] = emails


def _ensure_registry_current() -> None:
    """Rebuild the registry whenever the core has been (re)started underneath us."""
    global _registry_generation
    gen = getattr(xray.core, "config_generation", 0)
    if gen == _registry_generation:
        return
    cfg = getattr(xray.core, "last_config", None)
    if cfg is not None:
        _reset_registry_from_config(cfg)
    else:
        with _hot_lock:
            _registered.clear()
    _registry_generation = gen


def _api_add_user(inbound_tag: str, account: "Account") -> None:
    try:
        xray.api.add_inbound_user(tag=inbound_tag, user=account, timeout=10)
    except (xray.exc.EmailExistsError, xray.exc.ConnectionError):
        pass
    with _hot_lock:
        _registered.setdefault(inbound_tag, set()).add(account.email)


def _api_remove_user(inbound_tag: str, email: str) -> None:
    try:
        xray.api.remove_inbound_user(tag=inbound_tag, email=email, timeout=10)
    except (
        xray.exc.EmailNotFoundError,
        xray.exc.ConnectionError,
        xray.exc.TagNotFoundError,
    ):
        pass
    with _hot_lock:
        s = _registered.get(inbound_tag)
        if s:
            s.discard(email)


def _inbound_requires_restart_on_change(inbound_tag: str) -> bool:
    """True when the inbound cannot be hot-mutated (SS-2022 today)."""
    inbound = xray.config.inbounds_by_tag.get(inbound_tag)
    if not inbound and xray.core.last_config is not None:
        inbound = xray.core.last_config.get_inbound(inbound_tag) or {}
    if not inbound:
        return False
    if inbound.get("protocol") != "shadowsocks":
        return False
    from xray_api.types.account import is_ss2022

    method = inbound.get("ss_method") or (inbound.get("settings") or {}).get("method") or ""
    return is_ss2022(method)


def _core_user_diff_requires_restart(
    desired: dict[str, dict[str, "Account"]],
    snapshot: dict[str, set[str]],
) -> bool:
    """True only when a **restart-only** inbound (SS-2022) has drifted.

    Adds *and* removes on hot-capable inbounds are applied live through the
    handler gRPC API (see ``hot_sync_main_core``), exactly like 3x-ui's
    ``AlterInbound`` add/remove-user path, so they never need a restart and
    unrelated users keep their sessions. Only SS-2022 handlers — which cannot be
    hot-mutated (gRPC AddUser panics the core) — still force a full rebuild when
    their user set changes.
    """
    all_tags = set(snapshot) | set(desired)
    for tag in all_tags:
        if not _inbound_requires_restart_on_change(tag):
            continue
        want = set(desired.get(tag, {}).keys())
        have = snapshot.get(tag, set())
        if want != have:
            return True
    return False


def hot_sync_main_core() -> bool:
    """Reconcile the live core's users with the DB via the handler API.

    Both **adds and removes** are applied live through the gRPC handler API so
    unrelated users' sessions are never dropped. Returns ``False`` — so the
    caller can fall back to a full restart — only when the core is down, its API
    is unreachable, or a restart-only inbound (SS-2022) has drifted.
    """
    if not xray.core.started or xray.core.restarting:
        return False

    # Liveness probe: if the API can't be reached a hot sync is impossible.
    try:
        xray.api.get_sys_stats(timeout=3)
    except Exception:
        return False

    # Build desired set *outside* the hot lock so a 500k-user DB scan cannot
    # block hot_disconnect_users / sync_main_core_user for the whole reconcile.
    desired = _build_desired_by_inbound()

    with _hot_lock:
        _ensure_registry_current()
        snapshot = {tag: set(emails) for tag, emails in _registered.items()}

        if _core_user_diff_requires_restart(desired, snapshot):
            return False

        # Adds: push users the live core is missing.
        for tag, accounts in desired.items():
            if not _inbound_supports_hot_sync(tag):
                continue
            have = snapshot.get(tag, set())
            for email, account in accounts.items():
                if email not in have:
                    _api_add_user(tag, account)

        # Removes: drop users the live core still has but the DB no longer wants,
        # through the same live API. Blocks their *new* connections instantly
        # with zero impact on everyone else — no full-core restart.
        for tag, emails in snapshot.items():
            if not _inbound_supports_hot_sync(tag):
                continue
            want = set(desired.get(tag, {}).keys())
            for email in emails - want:
                _api_remove_user(tag, email)

    return True


def hot_disconnect_users(dbusers) -> bool:
    """Drop specific users from the live main core via the handler API.

    Blocks all *new* connections for these users instantly with zero impact on
    everyone else — no full-core restart (this is 3x-ui's behaviour). Returns
    ``False`` only when the core is down or its API is unreachable, so the
    caller can fall back to a restart (the sole way to converge a dead core).

    SS-2022 inbounds cannot be hot-removed; those emails are intentionally left
    for the traffic-verified escalation (``enforce_disconnect_for_non_billable``)
    rather than forcing a restart that would disconnect the whole node for one
    user.
    """
    users = list(dbusers)
    if not users:
        return True
    if not xray.core.started or xray.core.restarting:
        return False
    try:
        xray.api.get_sys_stats(timeout=3)
    except Exception:
        return False

    emails = {f"{u.id}.{u.username}" for u in users}
    with _hot_lock:
        _ensure_registry_current()
        for tag, registered in list(_registered.items()):
            if not _inbound_supports_hot_sync(tag):
                continue
            for email in emails & set(registered):
                _api_remove_user(tag, email)
    return True


def sync_main_core_user(dbuser) -> None:
    """Push one user's proxy settings to the main core without restarting."""
    if dbuser.status not in (UserStatus.active, UserStatus.on_hold):
        # Never force-restart the whole core for one limited/disabled/expired
        # user — that disconnects every active session. Hot-remove only.
        hot_disconnect_users([dbuser])
        return
    if not xray.core.started or xray.core.restarting:
        return
    from app.utils.device_exclusivity import PROTO_XRAY, is_protocol_held, is_xray_proxy_held

    # Entire Xray family held (VLESS winner is WG/singbox) — drop all non-WG.
    if is_protocol_held(dbuser, PROTO_XRAY):
        hot_disconnect_users([dbuser])
        # Still push WireGuard/Finalmask accounts if those are not held.
    proxies = _proxy_settings_map(dbuser)
    email = f"{dbuser.id}.{dbuser.username}"
    with _hot_lock:
        _ensure_registry_current()
        for proxy_type, inbound_tags in dbuser.inbounds.items():
            pt = proxy_type.value if hasattr(proxy_type, "value") else str(proxy_type)
            if is_xray_proxy_held(dbuser, pt):
                for inbound_tag in inbound_tags:
                    if not _inbound_supports_hot_sync(inbound_tag):
                        continue
                    _api_remove_user(inbound_tag, email)
                continue
            for inbound_tag in inbound_tags:
                if not _inbound_supports_hot_sync(inbound_tag):
                    continue
                account = _account_for_inbound(
                    proxies, proxy_type, inbound_tag, email,
                    user_id=dbuser.id,
                    speed_limit_up=dbuser.speed_limit_up,
                    speed_limit_down=dbuser.speed_limit_down,
                )
                if account is None:
                    continue
                # remove-then-add so changed credentials take effect
                _api_remove_user(inbound_tag, email)
                _api_add_user(inbound_tag, account)


def _in_post_start_grace() -> bool:
    started_at = getattr(xray.core, "started_at", None)
    return started_at is not None and (time.time() - started_at) < _POST_START_GRACE_SEC


def _full_restart_sync(*, force: bool = False) -> None:
    global _last_full_restart_at
    now = time.time()
    if (
        not force
        and _last_full_restart_at
        and (now - _last_full_restart_at) < _FULL_RESTART_MIN_INTERVAL_SEC
    ):
        logger.debug("Skipping full Xray restart — min interval active")
        return
    config = xray.config.include_db_users()
    xray.core.restart(config, force=force)
    _last_full_restart_at = time.time()
    _ensure_registry_current()
    _apply_panel_traffic_limits(config)
    logger.info("Xray core restarted and synced with DB users")


def _apply_panel_traffic_limits(config) -> None:
    limits = (config or {}).get("traffic_limits") or []
    if not limits:
        return
    try:
        import sys
        from pathlib import Path

        node_dir = Path(__file__).resolve().parents[2] / "node"
        if str(node_dir) not in sys.path:
            sys.path.insert(0, str(node_dir))
        from speed_limit import SpeedLimitManager, port_limits_from_spec

        shaped = port_limits_from_spec({"traffic_limits": limits})
        if shaped:
            SpeedLimitManager().apply_ports(shaped)
    except Exception as exc:
        logger.warning("Panel SS tier speed limits not applied: %s", exc)


def sync_core_users_now(*, force_restart: bool = False) -> None:
    """Align main Xray with DB billable users (hot sync, restart only if needed).

    ``force_restart=True`` always rebuilds and restarts the core so existing
    sessions (xhttp, splithttp, SS-2022) drop immediately — hot API remove is
    not enough to cut live connections.
    """
    try:
        from app.migration.state import migration_active
    except ImportError:
        migration_active = lambda: False  # noqa: E731
    if migration_active():
        return
    if xray.core.restarting:
        return
    if not force_restart and _in_post_start_grace():
        return
    try:
        if force_restart:
            _full_restart_sync(force=True)
        elif hot_sync_main_core():
            logger.info("Xray core hot-synced with DB users")
        else:
            if _in_post_start_grace():
                return
            _full_restart_sync()
    except Exception:
        logger.exception("Hot sync failed; falling back to full core restart")
        try:
            _full_restart_sync()
        except Exception:
            logger.exception("Failed to sync Xray core with DB users")
    _sync_wireguard()


def reconcile_core_users() -> None:
    """Periodic safety net: ensure no billable user is missing from the core."""
    try:
        from app.migration.state import migration_active
    except ImportError:
        migration_active = lambda: False  # noqa: E731
    if migration_active():
        return
    if not xray.core.started or xray.core.restarting:
        return
    try:
        if not hot_sync_main_core():
            return
    except Exception:
        logger.debug("Periodic core reconcile skipped (core API unavailable)")


def schedule_core_sync(delay: float = _DEBOUNCE_SEC, *, full: bool = False) -> None:
    """Debounce rapid user changes into one sync.

    ``full=True`` skips hot-sync and rebuilds the core from ``include_db_users()``
    so policy speed limits and client levels take effect.
    """
    global _sync_timer

    def _run():
        global _sync_timer
        with _sync_lock:
            _sync_timer = None
        if full:
            _full_restart_sync(force=True)
        else:
            sync_core_users_now()

    with _sync_lock:
        if _sync_timer is not None:
            _sync_timer.cancel()
        _sync_timer = threading.Timer(delay, _run)
        _sync_timer.daemon = True
        _sync_timer.start()


def force_full_core_restart() -> None:
    """Rebuild Xray from DB immediately (policy / speed limits / SS-2022)."""
    with _sync_lock:
        global _sync_timer
        if _sync_timer is not None:
            _sync_timer.cancel()
            _sync_timer = None
    _full_restart_sync(force=True)


def apply_serving_state(*, immediate: bool = False) -> None:
    """Public entry: refresh Xray + WireGuard after any user status/quota change."""
    if immediate:
        sync_core_users_now()
    else:
        schedule_core_sync()
