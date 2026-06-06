"""Keep the live Xray core aligned with billable users in the database.

Design (principled, no needless disconnects):

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
from collections import defaultdict
from typing import TYPE_CHECKING

from app import xray
from app.db import GetDB, crud
from app.models.user import UserResponse, UserStatus
from xray_api.types.account import XTLSFlows

if TYPE_CHECKING:
    from xray_api.types.account import Account

logger = logging.getLogger("nexus-xray-serving")

_sync_lock = threading.Lock()
_sync_timer: threading.Timer | None = None
_DEBOUNCE_SEC = 1.5

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


def _account_for_inbound(user: UserResponse, proxy_type, inbound_tag: str, email: str) -> "Account | None":
    inbound = xray.config.inbounds_by_tag.get(inbound_tag, {})
    try:
        proxy_settings = user.proxies[proxy_type].dict(no_obj=True)
    except KeyError:
        return None
    account = proxy_type.account_model(email=email, **proxy_settings)
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
    """
    desired: dict[str, dict[str, Account]] = defaultdict(dict)

    with GetDB() as db:
        users = crud.get_users(db, status=[UserStatus.active, UserStatus.on_hold])
        for dbuser in users:
            user = UserResponse.model_validate(dbuser)
            email = f"{dbuser.id}.{dbuser.username}"
            for proxy_type, inbound_tags in user.inbounds.items():
                for inbound_tag in inbound_tags:
                    account = _account_for_inbound(user, proxy_type, inbound_tag, email)
                    if account is not None:
                        desired[inbound_tag][email] = account
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
    except (xray.exc.EmailNotFoundError, xray.exc.ConnectionError):
        pass
    with _hot_lock:
        s = _registered.get(inbound_tag)
        if s:
            s.discard(email)


def hot_sync_main_core() -> bool:
    """Reconcile the live core's users with the DB via the handler API.

    Returns ``False`` (so the caller can fall back to a restart) when the core
    is down or its API is unreachable.
    """
    if not xray.core.started or xray.core.restarting:
        return False

    # Liveness probe: if the API can't be reached a hot sync is impossible.
    try:
        xray.api.get_sys_stats(timeout=3)
    except Exception:
        return False

    with _hot_lock:
        _ensure_registry_current()
        desired = _build_desired_by_inbound()
        snapshot = {tag: set(emails) for tag, emails in _registered.items()}

        # Add every desired user the core is missing (idempotent: EmailExists ok).
        for tag, accounts in desired.items():
            have = snapshot.get(tag, set())
            for email, account in accounts.items():
                if email not in have:
                    _api_add_user(tag, account)

        # Remove anything we previously pushed that is no longer billable.
        for tag, have in snapshot.items():
            keep = set(desired.get(tag, {}).keys())
            for email in have - keep:
                _api_remove_user(tag, email)

    return True


def sync_main_core_user(dbuser) -> None:
    """Push one user's proxy settings to the main core without restarting."""
    if not xray.core.started or xray.core.restarting:
        return
    user = UserResponse.model_validate(dbuser)
    email = f"{dbuser.id}.{dbuser.username}"
    with _hot_lock:
        _ensure_registry_current()
        for proxy_type, inbound_tags in user.inbounds.items():
            for inbound_tag in inbound_tags:
                account = _account_for_inbound(user, proxy_type, inbound_tag, email)
                if account is None:
                    continue
                # remove-then-add so changed credentials take effect
                _api_remove_user(inbound_tag, email)
                _api_add_user(inbound_tag, account)


def _full_restart_sync() -> None:
    config = xray.config.include_db_users()
    xray.core.restart(config)
    _ensure_registry_current()
    logger.info("Xray core restarted and synced with DB users")


def sync_core_users_now() -> None:
    """Align main Xray with DB billable users (hot sync, restart only if needed)."""
    try:
        if hot_sync_main_core():
            logger.info("Xray core hot-synced with DB users")
        else:
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
        if not hot_sync_main_core():
            return
    except Exception:
        logger.exception("Periodic core reconcile failed")


def schedule_core_sync(delay: float = _DEBOUNCE_SEC) -> None:
    """Debounce rapid user changes into one sync."""
    global _sync_timer

    def _run():
        global _sync_timer
        with _sync_lock:
            _sync_timer = None
        sync_core_users_now()

    with _sync_lock:
        if _sync_timer is not None:
            _sync_timer.cancel()
        _sync_timer = threading.Timer(delay, _run)
        _sync_timer.daemon = True
        _sync_timer.start()


def apply_serving_state(*, immediate: bool = False) -> None:
    """Public entry: refresh Xray + WireGuard after any user status/quota change."""
    if immediate:
        sync_core_users_now()
    else:
        schedule_core_sync()
