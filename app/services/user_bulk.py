"""Fast bulk user operations (inbound assign/remove, preview, bulk create)."""
from __future__ import annotations

import secrets
import string
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app import logger, xray
from app.db import Session, crud
from app.db.models import Admin, Proxy, ProxyInbound, ProxyTypes, User
from app.models.proxy import ProxySettings
from app.models.user import (
    UserCreate,
    UserDataLimitResetStrategy,
    UserModify,
    UserStatus,
    UserStatusCreate,
)
from app.xray.inbound_match import inbound_matches_proxy, repair_shadowsocks_proxy_settings


class BulkInboundScope(str, Enum):
    all = "all"
    selected = "selected"
    filtered = "filtered"


class UserListFilters(BaseModel):
    """Optional filters when scope is ``filtered`` (same as GET /users)."""

    status: Optional[UserStatus] = None
    search: Optional[str] = None
    protocol: Optional[str] = None
    inbound_tag: Optional[str] = None
    source_slug: Optional[str] = None
    expiring_within_days: Optional[int] = Field(None, ge=1, le=365)
    near_limit_percent: Optional[int] = Field(None, ge=1, le=100)


class BulkInboundAction(str, Enum):
    add = "add"
    remove = "remove"


class BulkInboundRequest(BaseModel):
    inbound_tag: str = Field(..., min_length=1, max_length=256)
    action: BulkInboundAction
    scope: BulkInboundScope = BulkInboundScope.selected
    usernames: List[str] = Field(default_factory=list)
    status: Optional[UserStatus] = None
    filters: Optional[UserListFilters] = None
    ensure_proxy: bool = True


class BulkInboundPreview(BaseModel):
    inbound_tag: str
    action: BulkInboundAction
    total_users: int
    would_apply: int
    already_set: int
    incompatible: int
    missing_proxy: int


class BulkInboundResult(BaseModel):
    inbound_tag: str
    action: BulkInboundAction
    applied: int
    skipped: int
    failed: int
    errors: List[str] = Field(default_factory=list)
    duration_ms: int


def _proxy_type_for_inbound(inbound: dict) -> Optional[ProxyTypes]:
    proto = str(inbound.get("protocol") or "").lower()
    settings = inbound.get("settings") or {}
    if proto == "wireguard":
        if settings.get("nexusPanelKind") == "amneziawg":
            return ProxyTypes.WireGuard
        return ProxyTypes.WireGuard
    try:
        return ProxyTypes(proto)
    except ValueError:
        return None


def _inbound_meta(inbound_tag: str) -> dict:
    inbound = xray.config.inbounds_by_tag.get(inbound_tag)
    if not inbound:
        raise ValueError(f"Inbound '{inbound_tag}' does not exist in the active Xray config")
    return inbound


def _iter_target_users(
    db: Session,
    *,
    admin: Optional[Admin],
    scope: BulkInboundScope,
    usernames: Iterable[str],
    status: Optional[UserStatus],
    filters: Optional[UserListFilters] = None,
) -> List[User]:
    admins = None
    if admin and not admin.is_sudo:
        admins = [admin.username]

    if scope == BulkInboundScope.selected:
        names = [u.strip() for u in usernames if u and u.strip()]
        if not names:
            raise ValueError("usernames required when scope is 'selected'")
        users, _ = crud.get_users(
            db,
            usernames=names,
            admins=admins,
            return_with_count=True,
        )
        return users

    list_filters = filters or UserListFilters()
    effective_status = status if status is not None else list_filters.status

    if scope == BulkInboundScope.filtered:
        users, _ = crud.get_users(
            db,
            admins=admins,
            status=effective_status,
            search=list_filters.search,
            protocol=list_filters.protocol,
            inbound_tag=list_filters.inbound_tag,
            source_slug=list_filters.source_slug,
            expiring_within_days=list_filters.expiring_within_days,
            near_limit_percent=list_filters.near_limit_percent,
            return_with_count=True,
        )
        return users

    users, _ = crud.get_users(db, admins=admins, return_with_count=True)
    return users


def _current_tags(user: User, proxy_type: ProxyTypes) -> List[str]:
    return list((user.inbounds or {}).get(proxy_type, []))


def _plan_change(
    user: User,
    inbound_tag: str,
    inbound: dict,
    proxy_type: ProxyTypes,
    action: BulkInboundAction,
    *,
    ensure_proxy: bool,
) -> Tuple[Optional[UserModify], str]:
    """Return (UserModify, reason) — reason empty when modify should run."""
    tags = _current_tags(user, proxy_type)
    has_tag = inbound_tag in tags
    proxy = next((p for p in user.proxies if p.type == proxy_type), None)

    if action == BulkInboundAction.add:
        if has_tag:
            return None, "already_set"
        if proxy and not inbound_matches_proxy(
            proxy_type, inbound_tag, proxy.settings or {}, inbound_meta=inbound
        ):
            return None, "incompatible"
        if not proxy and not ensure_proxy:
            return None, "missing_proxy"
        new_tags = tags + [inbound_tag]
        modify = UserModify(inbounds={proxy_type: new_tags})
        if not proxy:
            modify.proxies = {proxy_type: {}}
        return modify, ""

    # remove
    if not has_tag:
        return None, "already_set"
    new_tags = [t for t in tags if t != inbound_tag]
    modify = UserModify(inbounds={proxy_type: new_tags})
    if not new_tags:
        if proxy:
            keep_proxies = {
                p.type: {}
                for p in user.proxies
                if p.type != proxy_type
            }
            modify.proxies = keep_proxies
    return modify, ""


def preview_bulk_inbound(
    db: Session,
    body: BulkInboundRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkInboundPreview:
    inbound = _inbound_meta(body.inbound_tag)
    proxy_type = _proxy_type_for_inbound(inbound)
    if proxy_type is None:
        raise ValueError(f"Inbound protocol '{inbound.get('protocol')}' is not assignable to users")

    users = _iter_target_users(
        db,
        admin=admin,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )
    would_apply = already_set = incompatible = missing_proxy = 0
    for user in users:
        modify, reason = _plan_change(
            user,
            body.inbound_tag,
            inbound,
            proxy_type,
            body.action,
            ensure_proxy=body.ensure_proxy,
        )
        if modify is not None:
            would_apply += 1
        elif reason == "already_set":
            already_set += 1
        elif reason == "incompatible":
            incompatible += 1
        elif reason == "missing_proxy":
            missing_proxy += 1

    return BulkInboundPreview(
        inbound_tag=body.inbound_tag,
        action=body.action,
        total_users=len(users),
        would_apply=would_apply,
        already_set=already_set,
        incompatible=incompatible,
        missing_proxy=missing_proxy,
    )


def _fast_add_inbound(proxy: Proxy, inbound_tag: str) -> None:
    """Whitelist one inbound by dropping it from the proxy exclusion list."""
    proxy.excluded_inbounds = [i for i in proxy.excluded_inbounds if i.tag != inbound_tag]


def _fast_remove_inbound(proxy: Proxy, inbound_record: ProxyInbound, inbound_tag: str) -> None:
    """Remove one inbound from the effective whitelist via exclusion."""
    if any(i.tag == inbound_tag for i in proxy.excluded_inbounds):
        return
    proxy.excluded_inbounds = list(proxy.excluded_inbounds) + [inbound_record]


def _repair_ss_after_inbound_change(
    proxy: Proxy,
    proxy_type: ProxyTypes,
    target_tags: List[str],
) -> None:
    if proxy_type != ProxyTypes.Shadowsocks:
        return
    patched = repair_shadowsocks_proxy_settings(proxy.settings, target_tags)
    if patched:
        proxy.settings = patched


def apply_bulk_inbound(
    db: Session,
    body: BulkInboundRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkInboundResult:
    from app import xray as xray_mod

    started = time.perf_counter()
    inbound = _inbound_meta(body.inbound_tag)
    proxy_type = _proxy_type_for_inbound(inbound)
    if proxy_type is None:
        raise ValueError(f"Inbound protocol '{inbound.get('protocol')}' is not assignable to users")

    users = _iter_target_users(
        db,
        admin=admin,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )

    inbound_cache: Dict[str, ProxyInbound] = {}
    inbound_record = crud.get_or_create_inbound(
        db,
        body.inbound_tag,
        inbound_cache=inbound_cache,
        commit=False,
    )

    applied = skipped = failed = 0
    errors: List[str] = []
    touched_active = False
    now = datetime.utcnow()

    for user in users:
        modify, reason = _plan_change(
            user,
            body.inbound_tag,
            inbound,
            proxy_type,
            body.action,
            ensure_proxy=body.ensure_proxy,
        )
        if modify is None:
            skipped += 1
            continue
        try:
            proxy = next((p for p in user.proxies if p.type == proxy_type), None)
            target_tags = list(modify.inbounds.get(proxy_type, []))

            if modify.proxies is not None:
                # New proxy and/or protocol removal — full update path, batched commit.
                crud.update_user(
                    db,
                    user,
                    modify,
                    commit=False,
                    inbound_cache=inbound_cache,
                )
            elif proxy is None:
                skipped += 1
                continue
            elif body.action == BulkInboundAction.add:
                _fast_add_inbound(proxy, body.inbound_tag)
                _repair_ss_after_inbound_change(proxy, proxy_type, target_tags)
            else:
                _fast_remove_inbound(proxy, inbound_record, body.inbound_tag)
                _repair_ss_after_inbound_change(proxy, proxy_type, target_tags)

            user.edit_at = now
            if user.status in (UserStatus.active, UserStatus.on_hold):
                touched_active = True
            applied += 1
        except Exception as exc:
            failed += 1
            msg = f"{user.username}: {exc}"
            errors.append(msg)
            if len(errors) >= 20:
                errors.append("…")
                break
            logger.warning("bulk inbound %s for %s failed: %s", body.action, user.username, exc)

    if applied:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    if applied and touched_active:
        xray_mod.operations.schedule_core_sync()
        try:
            xray_mod.operations._sync_wireguard()
        except Exception:
            pass

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "bulk inbound %s tag=%s scope=%s applied=%s skipped=%s failed=%s %sms",
        body.action.value,
        body.inbound_tag,
        body.scope.value,
        applied,
        skipped,
        failed,
        duration_ms,
    )
    return BulkInboundResult(
        inbound_tag=body.inbound_tag,
        action=body.action,
        applied=applied,
        skipped=skipped,
        failed=failed,
        errors=errors,
        duration_ms=duration_ms,
    )


class BulkUserCreateBody(BaseModel):
    """Create many users with the same settings (template optional)."""

    count: int = Field(ge=1, le=500)
    username_prefix: Optional[str] = ""
    username_suffix: Optional[str] = ""
    status: UserStatusCreate = UserStatusCreate.active
    template_id: Optional[int] = None
    proxies: Dict[ProxyTypes, Dict[str, Any]] = Field(default_factory=dict)
    inbounds: Dict[ProxyTypes, List[str]] = Field(default_factory=dict)
    # Bind created users to a subscription panel endpoint (p1…p9) so client
    # links use that panel's domain/port/path (via SubscriptionTokenAlias).
    subscription_endpoint_id: Optional[int] = None
    data_limit: Optional[int] = 0
    expire: Optional[int] = 0
    data_limit_reset_strategy: UserDataLimitResetStrategy = (
        UserDataLimitResetStrategy.no_reset
    )
    note: Optional[str] = ""
    client_profile: Optional[str] = "normal"
    routing_preset: Optional[str] = None
    dns_policy: Optional[dict] = None
    session_limit_minutes: Optional[int] = None
    speed_limit_up: Optional[int] = None
    speed_limit_down: Optional[int] = None
    device_limit: Optional[int] = None
    on_hold_expire_duration: Optional[int] = None

    @model_validator(mode="after")
    def _require_proxies_without_template(self):
        if self.template_id is None and not self.proxies:
            raise ValueError("Select at least one protocol (or pick a template)")
        return self


class BulkCreatedUserLink(BaseModel):
    username: str
    subscription_url: str = ""
    public_subscription_url: str = ""
    sub_token: Optional[str] = None


class BulkUserCreateResult(BaseModel):
    created: int
    usernames: List[str] = Field(default_factory=list)
    users: List[BulkCreatedUserLink] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    duration_ms: int


def _user_create_from_bulk_body(
    body: BulkUserCreateBody,
    *,
    username: str,
    db: Session,
) -> UserCreate:
    if body.template_id is not None:
        from app.routers.user import _user_create_from_db_template

        db_tpl = crud.get_user_template(db, body.template_id)
        if db_tpl is None:
            raise ValueError(f"Template {body.template_id} not found")
        spec = _user_create_from_db_template(db_tpl, username=username, status=body.status)
        data = spec.model_dump()
        data["username"] = username
    else:
        proxies = {
            ptype: ProxySettings.from_dict(ptype, settings if isinstance(settings, dict) else {})
            for ptype, settings in body.proxies.items()
        }
        data = {
            "username": username,
            "status": body.status,
            "proxies": proxies,
            "inbounds": dict(body.inbounds),
            "data_limit": body.data_limit,
            "expire": body.expire,
            "data_limit_reset_strategy": body.data_limit_reset_strategy,
            "note": body.note or "",
            "client_profile": body.client_profile or "normal",
            "routing_preset": body.routing_preset,
            "dns_policy": body.dns_policy,
            "session_limit_minutes": body.session_limit_minutes,
            "speed_limit_up": body.speed_limit_up,
            "speed_limit_down": body.speed_limit_down,
            "device_limit": body.device_limit,
            "on_hold_expire_duration": body.on_hold_expire_duration,
        }
        return UserCreate(**data)

    if body.proxies:
        data["proxies"] = {
            ptype: ProxySettings.from_dict(ptype, settings if isinstance(settings, dict) else {})
            for ptype, settings in body.proxies.items()
        }
    if body.inbounds:
        data["inbounds"] = dict(body.inbounds)
    scalar_keys = (
        "status",
        "data_limit",
        "expire",
        "data_limit_reset_strategy",
        "note",
        "client_profile",
        "routing_preset",
        "dns_policy",
        "session_limit_minutes",
        "speed_limit_up",
        "speed_limit_down",
        "device_limit",
        "on_hold_expire_duration",
    )
    for key in scalar_keys:
        val = getattr(body, key)
        if val is not None:
            data[key] = val
    return UserCreate(**data)


def bulk_create_users(
    db: Session,
    body: BulkUserCreateBody,
    *,
    admin: Optional[Admin] = None,
) -> BulkUserCreateResult:
    from app import xray as xray_mod
    from app.routers.user import _ensure_protocol_enabled
    from app.subscription.panel_balance import (
        alias_token_for_username,
        bind_user_to_panel,
        ensure_panel_username,
        list_balance_panels,
        panel_user_count,
    )

    started = time.perf_counter()
    prefix = body.username_prefix or ""
    suffix = body.username_suffix or ""
    alphabet = string.ascii_lowercase + string.digits
    dbadmin = crud.get_admin(db, admin.username) if admin else None

    # Validate reseller quotas once — create_user would otherwise COUNT users
    # on every iteration (~500ms×N on large tables).
    if dbadmin is not None and dbadmin.max_users is not None:
        current = crud.get_users_count(db, admin=dbadmin)
        if current + int(body.count) > int(dbadmin.max_users):
            raise ValueError(
                f"Reseller user limit reached ({dbadmin.max_users}); "
                f"have {current}, requested {body.count}"
            )
    if (
        dbadmin is not None
        and not dbadmin.is_sudo
        and dbadmin.max_total_traffic is not None
        and int(dbadmin.users_usage or 0) >= int(dbadmin.max_total_traffic)
    ):
        raise ValueError(
            f"Reseller total-traffic limit reached ({dbadmin.max_total_traffic} bytes)"
        )

    pinned_ep = None
    if body.subscription_endpoint_id is not None:
        pinned_ep = crud.get_subscription_endpoint(db, body.subscription_endpoint_id)
        if pinned_ep is None or not pinned_ep.enabled:
            raise ValueError("Selected subscription panel endpoint was not found or is disabled")

    # Snapshot panel loads once, then assign locally (round-robin on least-loaded).
    # Old path called pick_least_loaded_panel → N COUNT queries *per user*.
    panel_counts: Dict[int, int] = {}
    balance_panels: List[Any] = []
    if pinned_ep is None:
        balance_panels = list_balance_panels(db)
        panel_counts = {ep.id: panel_user_count(db, ep.id) for ep in balance_panels}

    def _next_panel():
        if pinned_ep is not None:
            return pinned_ep
        if not balance_panels:
            return None
        ep = min(balance_panels, key=lambda e: (panel_counts.get(e.id, 0), e.id))
        panel_counts[ep.id] = int(panel_counts.get(ep.id, 0)) + 1
        return ep

    # Probe protocols once (was get_wireguard_nodes / get_singbox_nodes per user).
    sample_username = f"{prefix}probe{suffix}" or "bulkprobe"
    try:
        sample = _user_create_from_bulk_body(body, username=sample_username, db=db)
        for ptype in sample.proxies:
            _ensure_protocol_enabled(ptype, db)
        enabled_proxies = list(sample.proxies.keys())
    except Exception:
        raise

    inbound_cache: Dict[str, Any] = {}
    created: List[str] = []
    created_rows: List[Tuple[Any, Any, Optional[str]]] = []  # (db_user, panel_ep, alias_token)
    errors: List[str] = []
    COMMIT_EVERY = 50
    since_commit = 0

    for i in range(body.count):
        core = "".join(secrets.choice(alphabet) for _ in range(8))
        username = f"{prefix}{core}{suffix}"
        try:
            panel_ep = _next_panel()
            if panel_ep is not None:
                username = ensure_panel_username(username, panel_ep.slug)
            new_user = _user_create_from_bulk_body(body, username=username, db=db)
            if enabled_proxies:
                new_user.proxies = {
                    k: v for k, v in new_user.proxies.items() if k in enabled_proxies
                } or new_user.proxies
            # Savepoint so a duplicate username does not wipe the open batch.
            with db.begin_nested():
                db_user = crud.create_user(
                    db,
                    new_user,
                    admin=dbadmin,
                    commit=False,
                    inbound_cache=inbound_cache,
                    skip_admin_limits=True,
                )
                alias_token = None
                if panel_ep is not None and db_user is not None:
                    alias = bind_user_to_panel(
                        db,
                        user_id=db_user.id,
                        username=db_user.username,
                        endpoint=panel_ep,
                        source="bulk-create" if pinned_ep is not None else "auto-balance",
                        commit=False,
                    )
                    alias_token = getattr(alias, "token", None) or alias_token_for_username(
                        db_user.username, panel_ep.slug
                    )
            created.append(db_user.username if db_user else username)
            created_rows.append((db_user, panel_ep, alias_token))
            since_commit += 1
            if since_commit >= COMMIT_EVERY:
                db.commit()
                since_commit = 0
        except IntegrityError:
            errors.append(f"{username}: already exists")
        except Exception as exc:
            errors.append(f"{username}: {exc}")

    if since_commit:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    if created:
        needs_full = bool(body.speed_limit_up or body.speed_limit_down)
        if needs_full:
            from app.xray.serving import force_full_core_restart

            force_full_core_restart()
        else:
            xray_mod.operations.schedule_core_sync()
        try:
            xray_mod.operations._sync_wireguard()
        except Exception:
            pass

    # Build share links without UserResponse / generate_v2ray_links (was ~100ms+/user).
    from types import SimpleNamespace

    from app.subscription.public_url import _compose_endpoint_subscription_url
    from config import XRAY_SUBSCRIPTION_PATH, XRAY_SUBSCRIPTION_URL_PREFIX

    users_out: List[BulkCreatedUserLink] = []
    for db_user, panel_ep, alias_token in created_rows:
        username = getattr(db_user, "username", None) or ""
        try:
            sub_token = getattr(db_user, "sub_token", None)
            token = alias_token or sub_token
            mini = SimpleNamespace(
                id=getattr(db_user, "id", None),
                username=username,
                sub_token=sub_token,
            )
            pub = ""
            if panel_ep is not None and token:
                pub = _compose_endpoint_subscription_url(panel_ep, mini, token=token) or ""
            if not pub and token:
                prefix = (XRAY_SUBSCRIPTION_URL_PREFIX or "").strip().rstrip("/")
                if prefix:
                    pub = f"{prefix}/{XRAY_SUBSCRIPTION_PATH}/{token}/"
            if pub and not pub.endswith("/"):
                pub = f"{pub}/"
            users_out.append(
                BulkCreatedUserLink(
                    username=username,
                    subscription_url=pub,
                    public_subscription_url=pub,
                    sub_token=token,
                )
            )
        except Exception as exc:
            logger.warning("bulk create: failed to build link for %s: %s", username, exc)
            users_out.append(
                BulkCreatedUserLink(username=username, subscription_url="", public_subscription_url="")
            )

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info("bulk create users: created=%s failed=%s %sms", len(created), len(errors), duration_ms)
    return BulkUserCreateResult(
        created=len(created),
        usernames=created,
        users=users_out,
        errors=errors,
        duration_ms=duration_ms,
    )


class BulkExtendRequest(BaseModel):
    scope: BulkInboundScope = BulkInboundScope.selected
    usernames: List[str] = Field(default_factory=list)
    status: Optional[UserStatus] = None
    filters: Optional[UserListFilters] = None
    days: int = Field(0, ge=0, le=3650)
    add_data_bytes: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _require_change(self):
        if not self.days and not self.add_data_bytes:
            raise ValueError("Provide days and/or data to add")
        return self


class BulkResetUsageRequest(BaseModel):
    scope: BulkInboundScope = BulkInboundScope.selected
    usernames: List[str] = Field(default_factory=list)
    status: Optional[UserStatus] = None
    filters: Optional[UserListFilters] = None


class BulkUserActionResult(BaseModel):
    applied: int
    skipped: int
    failed: int
    errors: List[str] = Field(default_factory=list)
    duration_ms: int


class BulkEnableWireGuardKind(str, Enum):
    """Deprecated alias — prefer BulkNativeProtocol."""

    wireguard = "wireguard"
    amneziawg = "amneziawg"
    both = "both"


class BulkNativeProtocol(str, Enum):
    wireguard = "wireguard"
    amneziawg = "amneziawg"
    both = "both"  # WG + AmneziaWG on one proxy row
    hysteria2 = "hysteria2"
    tuic = "tuic"
    anytls = "anytls"


class BulkNativeAction(str, Enum):
    enable = "enable"
    disable = "disable"


class BulkNativeProtocolRequest(BaseModel):
    """Enable/disable a native node protocol (not an Xray inbound tag)."""

    protocol: BulkNativeProtocol
    action: BulkNativeAction = BulkNativeAction.enable
    scope: BulkInboundScope = BulkInboundScope.all
    usernames: List[str] = Field(default_factory=list)
    status: Optional[UserStatus] = None
    filters: Optional[UserListFilters] = None
    # When true (default), block until kernel/sing-box sync (+ Finalmask flush)
    # finishes so ``applied`` is not confused with “peers are live.”
    wait_sync: bool = True


class BulkNativeProtocolPreview(BaseModel):
    protocol: str
    action: str
    total_users: int
    would_apply: int
    already_set: int


class BulkNativeProtocolResult(BaseModel):
    protocol: str
    action: str
    applied: int
    skipped: int
    failed: int
    errors: List[str] = Field(default_factory=list)
    duration_ms: int
    # Dataplane converge (absent / null sync_ok means fire-and-forget).
    sync_pending: bool = False
    sync_ok: Optional[bool] = None
    sync_nodes: int = 0
    singbox_nodes: int = 0
    finalmask_reloaded: bool = False
    sync_ms: int = 0
    sync_error: Optional[str] = None


# Backward-compatible WireGuard-only shapes (map onto BulkNativeProtocol*).
class BulkEnableWireGuardRequest(BaseModel):
    scope: BulkInboundScope = BulkInboundScope.all
    usernames: List[str] = Field(default_factory=list)
    status: Optional[UserStatus] = None
    filters: Optional[UserListFilters] = None
    kind: BulkEnableWireGuardKind = BulkEnableWireGuardKind.wireguard


class BulkEnableWireGuardPreview(BaseModel):
    kind: str
    total_users: int
    would_apply: int
    already_set: int


class BulkEnableWireGuardResult(BaseModel):
    kind: str
    applied: int
    skipped: int
    failed: int
    errors: List[str] = Field(default_factory=list)
    duration_ms: int
    sync_pending: bool = False
    sync_ok: Optional[bool] = None
    sync_nodes: int = 0
    finalmask_reloaded: bool = False
    sync_ms: int = 0
    sync_error: Optional[str] = None


def _proxy_for_type(user: User, proxy_type: ProxyTypes) -> Optional[Proxy]:
    for proxy in user.proxies or []:
        if proxy.type == proxy_type:
            return proxy
    return None


def _wg_labels(settings: Optional[dict]) -> List[str]:
    from app.wireguard.kind import user_wg_stack_labels

    return user_wg_stack_labels(settings or {})


def _merge_wg_kind(current_labels: List[str], add: str) -> str:
    labels = set(current_labels)
    if add == "both":
        labels.update({"wireguard", "amneziawg"})
    else:
        labels.add(add)
    if "wireguard" in labels and "amneziawg" in labels:
        return "both"
    if "amneziawg" in labels:
        return "amneziawg"
    return "wireguard"


def _remove_wg_kind(current_labels: List[str], remove: str) -> Optional[str]:
    labels = set(current_labels)
    if remove == "both":
        return None
    labels.discard(remove)
    if not labels:
        return None
    if "wireguard" in labels and "amneziawg" in labels:
        return "both"
    if "amneziawg" in labels:
        return "amneziawg"
    return "wireguard"


def _native_proxy_type(protocol: BulkNativeProtocol) -> ProxyTypes:
    if protocol in (
        BulkNativeProtocol.wireguard,
        BulkNativeProtocol.amneziawg,
        BulkNativeProtocol.both,
    ):
        return ProxyTypes.WireGuard
    return ProxyTypes(protocol.value)


def _user_has_native(user: User, protocol: BulkNativeProtocol) -> bool:
    proxy_type = _native_proxy_type(protocol)
    proxy = _proxy_for_type(user, proxy_type)
    if proxy is None:
        return False
    if proxy_type != ProxyTypes.WireGuard:
        return True
    labels = _wg_labels(proxy.settings)
    if protocol == BulkNativeProtocol.both:
        return "wireguard" in labels and "amneziawg" in labels
    if protocol == BulkNativeProtocol.wireguard:
        return "wireguard" in labels
    if protocol == BulkNativeProtocol.amneziawg:
        return "amneziawg" in labels
    return False


def _apply_native_change(user: User, protocol: BulkNativeProtocol, action: BulkNativeAction) -> bool:
    """Mutate user proxies. Returns True if something changed."""
    from app.models.proxy import apply_proxy_patch
    from app.wireguard.kind import NXPANEL_WG_KIND

    proxy_type = _native_proxy_type(protocol)

    if proxy_type == ProxyTypes.WireGuard:
        wg = _proxy_for_type(user, ProxyTypes.WireGuard)
        labels = _wg_labels(wg.settings if wg else None)

        if action == BulkNativeAction.enable:
            new_kind = _merge_wg_kind(labels, protocol.value)
            if wg and set(_wg_labels(wg.settings)) == (
                {"wireguard", "amneziawg"} if new_kind == "both"
                else {new_kind}
            ):
                return False
            settings = apply_proxy_patch(
                ProxyTypes.WireGuard,
                wg.settings if wg else None,
                {NXPANEL_WG_KIND: new_kind},
            )
            if wg:
                wg.settings = settings
            else:
                user.proxies.append(Proxy(type=ProxyTypes.WireGuard, settings=settings))
            return True

        # disable
        if not wg:
            return False
        new_kind = _remove_wg_kind(labels, protocol.value)
        if new_kind is None:
            user.proxies.remove(wg)
            return True
        if set(_wg_labels(wg.settings)) == (
            {"wireguard", "amneziawg"} if new_kind == "both" else {new_kind}
        ):
            return False
        wg.settings = apply_proxy_patch(
            ProxyTypes.WireGuard,
            wg.settings,
            {NXPANEL_WG_KIND: new_kind},
        )
        return True

    # Hysteria2 / TUIC / AnyTLS
    proxy = _proxy_for_type(user, proxy_type)
    if action == BulkNativeAction.enable:
        if proxy is not None:
            return False
        user.proxies.append(
            Proxy(
                type=proxy_type,
                settings=apply_proxy_patch(proxy_type, None, {}),
            )
        )
        return True
    if proxy is None:
        return False
    user.proxies.remove(proxy)
    return True


def preview_bulk_native_protocol(
    db: Session,
    body: BulkNativeProtocolRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkNativeProtocolPreview:
    users = _iter_target_users(
        db,
        admin=admin,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )
    would_apply = already_set = 0
    for user in users:
        has = _user_has_native(user, body.protocol)
        want_change = (not has) if body.action == BulkNativeAction.enable else has
        if want_change:
            would_apply += 1
        else:
            already_set += 1
    return BulkNativeProtocolPreview(
        protocol=body.protocol.value,
        action=body.action.value,
        total_users=len(users),
        would_apply=would_apply,
        already_set=already_set,
    )


def apply_bulk_native_protocol(
    db: Session,
    body: BulkNativeProtocolRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkNativeProtocolResult:
    """Add/remove native protocol proxy rows without wiping other protocols."""
    from app.wireguard.converge import converge_after_bulk_native, pending_sync_meta

    started = time.perf_counter()
    users = _iter_target_users(
        db,
        admin=admin,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )
    applied = skipped = failed = 0
    errors: List[str] = []
    edit_at = datetime.utcnow()
    sync_meta = pending_sync_meta() if not body.wait_sync else {
        "sync_pending": False,
        "sync_ok": True,
        "sync_nodes": 0,
        "singbox_nodes": 0,
        "finalmask_reloaded": False,
        "sync_error": None,
        "sync_ms": 0,
    }

    for user in users:
        try:
            changed = _apply_native_change(user, body.protocol, body.action)
            if not changed:
                skipped += 1
                continue
            user.edit_at = edit_at
            db.add(user)
            applied += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{user.username}: {exc}")
            if len(errors) >= 20:
                errors.append("…")
                break

    if applied:
        db.commit()
        if body.wait_sync:
            sync_meta = converge_after_bulk_native(
                protocol=body.protocol.value,
                wait_finalmask=True,
            )
        else:
            from app import xray as xray_mod

            xray_mod.operations._sync_wireguard()
            sync_meta = pending_sync_meta()

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "bulk native protocol=%s action=%s scope=%s applied=%s skipped=%s failed=%s "
        "sync_ok=%s sync_pending=%s %sms",
        body.protocol.value,
        body.action.value,
        body.scope.value,
        applied,
        skipped,
        failed,
        sync_meta.get("sync_ok"),
        sync_meta.get("sync_pending"),
        duration_ms,
    )
    return BulkNativeProtocolResult(
        protocol=body.protocol.value,
        action=body.action.value,
        applied=applied,
        skipped=skipped,
        failed=failed,
        errors=errors,
        duration_ms=duration_ms,
        sync_pending=bool(sync_meta.get("sync_pending")),
        sync_ok=sync_meta.get("sync_ok"),
        sync_nodes=int(sync_meta.get("sync_nodes") or 0),
        singbox_nodes=int(sync_meta.get("singbox_nodes") or 0),
        finalmask_reloaded=bool(sync_meta.get("finalmask_reloaded")),
        sync_ms=int(sync_meta.get("sync_ms") or 0),
        sync_error=sync_meta.get("sync_error"),
    )


def preview_bulk_enable_wireguard(
    db: Session,
    body: BulkEnableWireGuardRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkEnableWireGuardPreview:
    mapped = BulkNativeProtocolRequest(
        protocol=BulkNativeProtocol(body.kind.value),
        action=BulkNativeAction.enable,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )
    p = preview_bulk_native_protocol(db, mapped, admin=admin)
    return BulkEnableWireGuardPreview(
        kind=p.protocol,
        total_users=p.total_users,
        would_apply=p.would_apply,
        already_set=p.already_set,
    )


def apply_bulk_enable_wireguard(
    db: Session,
    body: BulkEnableWireGuardRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkEnableWireGuardResult:
    mapped = BulkNativeProtocolRequest(
        protocol=BulkNativeProtocol(body.kind.value),
        action=BulkNativeAction.enable,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )
    r = apply_bulk_native_protocol(db, mapped, admin=admin)
    return BulkEnableWireGuardResult(
        kind=r.protocol,
        applied=r.applied,
        skipped=r.skipped,
        failed=r.failed,
        errors=r.errors,
        duration_ms=r.duration_ms,
        sync_pending=r.sync_pending,
        sync_ok=r.sync_ok,
        sync_nodes=r.sync_nodes,
        finalmask_reloaded=r.finalmask_reloaded,
        sync_ms=r.sync_ms,
        sync_error=r.sync_error,
    )


def apply_bulk_extend(
    db: Session,
    body: BulkExtendRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkUserActionResult:
    from app import xray as xray_mod

    started = time.perf_counter()
    users = _iter_target_users(
        db,
        admin=admin,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )
    now_ts = int(time.time())
    delta = body.days * 86400
    add_data = body.add_data_bytes
    applied = skipped = failed = 0
    errors: List[str] = []
    touched_active = False
    edit_at = datetime.utcnow()

    for user in users:
        try:
            changed = False
            if delta:
                base = user.expire if user.expire and user.expire > now_ts else now_ts
                new_expire = base + delta
                if user.expire != new_expire:
                    user.expire = new_expire
                    changed = True
            # Only top up a real quota — unlimited (0/None) stays unlimited.
            if add_data and user.data_limit and user.data_limit > 0:
                user.data_limit = user.data_limit + add_data
                changed = True

            if not changed:
                skipped += 1
                continue

            # Intelligent reactivation after granting more time/quota.
            if user.status == UserStatus.expired and user.expire and user.expire > now_ts:
                user.status = UserStatus.active
            if user.status == UserStatus.limited and (
                not user.data_limit or (user.used_traffic or 0) < user.data_limit
            ):
                user.status = UserStatus.active

            user.edit_at = edit_at
            db.add(user)
            if user.status in (UserStatus.active, UserStatus.on_hold):
                touched_active = True
            applied += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{user.username}: {exc}")
            if len(errors) >= 20:
                errors.append("…")
                break

    if applied:
        db.commit()
        if touched_active:
            xray_mod.operations.schedule_core_sync()

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "bulk extend days=%s data=%s scope=%s applied=%s skipped=%s failed=%s %sms",
        body.days,
        add_data,
        body.scope.value,
        applied,
        skipped,
        failed,
        duration_ms,
    )
    return BulkUserActionResult(
        applied=applied,
        skipped=skipped,
        failed=failed,
        errors=errors,
        duration_ms=duration_ms,
    )


def apply_bulk_reset_usage(
    db: Session,
    body: BulkResetUsageRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkUserActionResult:
    from app import xray as xray_mod
    from app.db.models import UserUsageResetLogs

    started = time.perf_counter()
    users = _iter_target_users(
        db,
        admin=admin,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )
    applied = skipped = failed = 0
    errors: List[str] = []
    touched_active = False

    for user in users:
        try:
            if user.used_traffic == 0 and not user.node_usages:
                skipped += 1
                continue
            usage_log = UserUsageResetLogs(
                user=user,
                used_traffic_at_reset=user.used_traffic,
            )
            db.add(usage_log)
            user.used_traffic = 0
            user.used_traffic_up = 0
            user.used_traffic_down = 0
            user.overage_traffic = 0
            user.node_usages.clear()
            if user.status not in (UserStatus.expired, UserStatus.disabled):
                user.status = UserStatus.active
            if user.next_plan:
                db.delete(user.next_plan)
                user.next_plan = None
            db.add(user)
            if user.status in (UserStatus.active, UserStatus.on_hold):
                touched_active = True
            applied += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{user.username}: {exc}")
            if len(errors) >= 20:
                errors.append("…")
                break

    if applied:
        db.commit()
        if touched_active:
            xray_mod.operations.schedule_core_sync()

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "bulk reset usage scope=%s applied=%s skipped=%s failed=%s %sms",
        body.scope.value,
        applied,
        skipped,
        failed,
        duration_ms,
    )
    return BulkUserActionResult(
        applied=applied,
        skipped=skipped,
        failed=failed,
        errors=errors,
        duration_ms=duration_ms,
    )


def _sync_after_membership_change() -> None:
    """Rebuild the running data-plane after users are removed/toggled.

    One resync (instead of N per-user calls) keeps ``delete all`` fast even
    with thousands of users while ensuring the live cores match the DB.
    """
    from app import xray as xray_mod

    try:
        xray_mod.operations.schedule_core_sync()
    except Exception:
        logger.exception("bulk: core resync failed")
    try:
        xray_mod.operations._sync_wireguard()
    except Exception:
        logger.exception("bulk: WireGuard resync failed")
    try:
        from app.singbox.operations import sync_user_change as singbox_sync

        singbox_sync()
    except Exception:
        logger.exception("bulk: sing-box resync failed")


# ─────────────────────────── bulk delete ───────────────────────────

class BulkDeleteRequest(BaseModel):
    scope: BulkInboundScope = BulkInboundScope.selected
    usernames: List[str] = Field(default_factory=list)
    statuses: List[UserStatus] = Field(default_factory=list)
    filters: Optional[UserListFilters] = None


class BulkDeleteResult(BaseModel):
    deleted: int
    duration_ms: int


def _iter_delete_targets(
    db: Session,
    *,
    admin: Optional[Admin],
    scope: BulkInboundScope,
    usernames: Iterable[str],
    statuses: List[UserStatus],
    filters: Optional[UserListFilters],
) -> List[User]:
    admins = None
    if admin and not admin.is_sudo:
        admins = [admin.username]

    if scope == BulkInboundScope.selected:
        names = [u.strip() for u in usernames if u and u.strip()]
        if not names:
            raise ValueError("usernames required when scope is 'selected'")
        users, _ = crud.get_users(
            db, usernames=names, admins=admins, return_with_count=True
        )
        return users

    if scope == BulkInboundScope.filtered:
        lf = filters or UserListFilters()
        status_arg = list(statuses) if statuses else lf.status
        users, _ = crud.get_users(
            db,
            admins=admins,
            status=status_arg,
            search=lf.search,
            protocol=lf.protocol,
            inbound_tag=lf.inbound_tag,
            source_slug=lf.source_slug,
            expiring_within_days=lf.expiring_within_days,
            near_limit_percent=lf.near_limit_percent,
            return_with_count=True,
        )
        return users

    users, _ = crud.get_users(db, admins=admins, return_with_count=True)
    return users


def apply_bulk_delete(
    db: Session,
    body: BulkDeleteRequest,
    *,
    admin: Optional[Admin] = None,
    progress_cb=None,
    chunk_size: int = 200,
) -> BulkDeleteResult:
    """Delete matching users, in chunks so large filters stay tractable.

    ``progress_cb(processed_delta, deleted_delta)`` is optional and lets a
    background job stream live counts to the UI without holding the HTTP
    request open (large deletes otherwise outlive reverse-proxy timeouts).
    """
    started = time.perf_counter()
    users = _iter_delete_targets(
        db,
        admin=admin,
        scope=body.scope,
        usernames=body.usernames,
        statuses=body.statuses,
        filters=body.filters,
    )
    # Snapshot ids + "was any active" up front — after the first chunk commits
    # the original ORM instances are expired/detached.
    user_ids = [int(u.id) for u in users]
    touched_active = any(
        u.status in (UserStatus.active, UserStatus.on_hold) for u in users
    )
    count = len(user_ids)
    deleted = 0

    if count:
        from app.db.models import User as DBUser

        step = max(1, int(chunk_size or 200))
        for i in range(0, count, step):
            batch_ids = user_ids[i : i + step]
            batch = (
                db.query(DBUser).filter(DBUser.id.in_(batch_ids)).all()
            )
            if batch:
                crud.remove_users(db, batch)
                deleted += len(batch)
            if progress_cb:
                try:
                    progress_cb(len(batch_ids), len(batch))
                except Exception:
                    pass

        if touched_active:
            _sync_after_membership_change()

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "bulk delete scope=%s statuses=%s deleted=%s %sms",
        body.scope.value,
        [s.value for s in body.statuses],
        deleted,
        duration_ms,
    )
    return BulkDeleteResult(deleted=deleted, duration_ms=duration_ms)


# ─────────────────────────── bulk enable / disable ───────────────────────────

class BulkStatusAction(str, Enum):
    enable = "enable"
    disable = "disable"


class BulkStatusRequest(BaseModel):
    scope: BulkInboundScope = BulkInboundScope.selected
    usernames: List[str] = Field(default_factory=list)
    status: Optional[UserStatus] = None
    filters: Optional[UserListFilters] = None
    action: BulkStatusAction


def _reactivated_status(user: User, now_ts: int) -> UserStatus:
    """Pick the correct live status when re-enabling a disabled user."""
    if user.expire and user.expire > 0 and user.expire <= now_ts:
        return UserStatus.expired
    if user.data_limit and user.data_limit > 0 and (user.used_traffic or 0) >= user.data_limit:
        return UserStatus.limited
    return UserStatus.active


def apply_bulk_status(
    db: Session,
    body: BulkStatusRequest,
    *,
    admin: Optional[Admin] = None,
) -> BulkUserActionResult:
    started = time.perf_counter()
    users = _iter_target_users(
        db,
        admin=admin,
        scope=body.scope,
        usernames=body.usernames,
        status=body.status,
        filters=body.filters,
    )
    now_ts = int(time.time())
    now = datetime.utcnow()
    applied = skipped = failed = 0
    errors: List[str] = []
    touched_core = False

    for user in users:
        try:
            if body.action == BulkStatusAction.disable:
                if user.status == UserStatus.disabled:
                    skipped += 1
                    continue
                was_live = user.status in (UserStatus.active, UserStatus.on_hold)
                user.status = UserStatus.disabled
                user.online_at = None
                if was_live:
                    touched_core = True
            else:  # enable
                if user.status != UserStatus.disabled:
                    skipped += 1
                    continue
                new_status = _reactivated_status(user, now_ts)
                user.status = new_status
                if new_status in (UserStatus.active, UserStatus.on_hold):
                    touched_core = True

            user.last_status_change = now
            user.edit_at = now
            db.add(user)
            applied += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{user.username}: {exc}")
            if len(errors) >= 20:
                errors.append("…")
                break

    if applied and touched_core:
        db.commit()
        _sync_after_membership_change()
    elif applied:
        db.commit()

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "bulk status action=%s scope=%s applied=%s skipped=%s failed=%s %sms",
        body.action.value,
        body.scope.value,
        applied,
        skipped,
        failed,
        duration_ms,
    )
    return BulkUserActionResult(
        applied=applied,
        skipped=skipped,
        failed=failed,
        errors=errors,
        duration_ms=duration_ms,
    )
