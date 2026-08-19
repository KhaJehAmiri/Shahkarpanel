from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app import logger, xray
from app.db import Session, crud, get_db
from app.db.models import User
from app.dependencies import get_expired_users_list, get_validated_user, validate_dates
from app.models.admin import Admin
from app.models.proxy import ProxyTypes
from app.models.user import (
    UserCreate,
    UserDataLimitResetStrategy,
    UserModify,
    UserResponse,
    UsersResponse,
    UserStatus,
    UserStatusCreate,
    UsersUsagesResponse,
    UserUsagesResponse,
)
from app.rbac import require_permission
from app.services.user_bulk import (
    BulkDeleteRequest,
    BulkEnableWireGuardRequest,
    BulkExtendRequest,
    BulkInboundRequest,
    BulkNativeProtocolRequest,
    BulkResetUsageRequest,
    BulkStatusRequest,
    BulkUserCreateBody,
)
from app.utils import report, responses

_SKIP_LINKS = {"skip_default_links": True}


def _user_response(dbuser: User, *, share_links: bool = False) -> UserResponse:
    """Build a panel user payload without accidentally generating share links twice."""
    user = UserResponse.model_validate(dbuser, context=_SKIP_LINKS)
    if not share_links:
        return user
    from app.models.user import SubscriptionLinkItem
    from app.subscription.share import (
        collect_v2ray_share_link_items,
        collect_v2ray_share_links,
    )

    try:
        user.links = collect_v2ray_share_links(user, reverse=False)
        user.link_items = [
            SubscriptionLinkItem(**item)
            for item in collect_v2ray_share_link_items(user, reverse=False)
        ]
    except Exception:
        logger.exception("Failed to enrich share links for user %s", user.username)
    return user


def _enqueue_user_apply(db: Session, dbuser: User, action: str) -> None:
    """Persist WG identity if needed, then a durable outbox row + worker wake."""
    from app.sync.outbox import schedule_user_sync
    from app.wireguard.instant_sync import provision_and_sync_wireguard_user

    if action in ("add", "protocol_change"):
        try:
            provision_and_sync_wireguard_user(int(dbuser.id), push=False)
            db.refresh(dbuser)
        except Exception:
            logger.exception(
                "WG provision before outbox failed for %s", getattr(dbuser, "username", "?")
            )
    schedule_user_sync(db, dbuser, action)


router = APIRouter(tags=["User"], prefix="/api", responses={401: responses._401})


class UserFromTemplateCreate(BaseModel):
    username: str
    template_id: int
    status: UserStatusCreate = UserStatusCreate.active  # noqa: F821


class BulkFromTemplateCreate(BaseModel):
    template_id: int
    count: int
    status: UserStatusCreate = UserStatusCreate.active
    username_prefix: Optional[str] = None
    username_suffix: Optional[str] = None


def _user_create_from_db_template(db_tpl, *, username: str, status: UserStatusCreate) -> UserCreate:
    from app.models.user import NextPlanModel
    from app.models.user_template import NATIVE_TEMPLATE_MARKERS, UserTemplateResponse

    tpl = UserTemplateResponse.model_validate(db_tpl)
    if db_tpl.username_prefix:
        username = f"{db_tpl.username_prefix}{username}"
    if db_tpl.username_suffix:
        username = f"{db_tpl.username_suffix}{username}"

    proxies = {ptype: {} for ptype in tpl.inbounds}
    wg_kind = None
    for inbound in db_tpl.inbounds or []:
        if inbound.tag in NATIVE_TEMPLATE_MARKERS:
            tag_kind = inbound.tag.replace("__native:", "")
            if tag_kind == "amneziawg":
                wg_kind = "amneziawg" if wg_kind != "wireguard" else "both"
            elif tag_kind == "wireguard":
                wg_kind = "wireguard" if wg_kind != "amneziawg" else "both"
    if wg_kind and ProxyTypes.WireGuard in proxies:
        from app.wireguard.kind import SHAHKAR_WG_KIND

        proxies[ProxyTypes.WireGuard] = {SHAHKAR_WG_KIND: wg_kind}

    expire = 0
    if tpl.expire_duration:
        expire = int(
            (datetime.now(timezone.utc) + timedelta(seconds=tpl.expire_duration)).timestamp()
        )

    next_plan = None
    if getattr(db_tpl, "next_plan", None):
        next_plan = NextPlanModel.model_validate(db_tpl.next_plan)

    reset_strategy = getattr(db_tpl, "data_limit_reset_strategy", None)
    note = getattr(db_tpl, "note", None) or ""

    return UserCreate(
        username=username,
        proxies=proxies,
        inbounds=tpl.inbounds,
        data_limit=tpl.data_limit if tpl.data_limit is not None else 0,
        expire=expire,
        status=status,
        note=note,
        data_limit_reset_strategy=reset_strategy or UserDataLimitResetStrategy.no_reset,
        next_plan=next_plan,
    )


def _ensure_protocol_enabled(proxy_type, db: Session) -> None:
    """A protocol is usable when it has at least one inbound (Xray) or, for
    WireGuard (which is not an Xray inbound), at least one configured WG node."""
    if proxy_type == ProxyTypes.WireGuard:
        from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled
        from app.wireguard.xray_native import xray_native_wg_enabled

        wg_nodes = crud.get_wireguard_nodes(db)
        # Finalmask (xray-native WG) alone is enough — kernel plain/AWG are optional.
        if any(
            n.wireguard
            and (
                plain_wg_enabled(n.wireguard)
                or amneziawg_enabled(n.wireguard)
                or xray_native_wg_enabled(n.wireguard)
            )
            for n in wg_nodes
        ):
            return
        if xray.config.inbounds_by_protocol.get("amneziawg"):
            return
        raise HTTPException(
            status_code=400,
            detail="WireGuard / AmneziaWG / Finalmask has no configured node on your server",
        )
    if proxy_type == ProxyTypes.Hysteria2:
        nodes = crud.get_singbox_nodes(db)
        if not any(n.singbox and n.singbox.hysteria2_enabled for n in nodes):
            raise HTTPException(
                status_code=400,
                detail="Hysteria2 has no configured node on your server",
            )
        return
    if proxy_type == ProxyTypes.TUIC:
        nodes = crud.get_singbox_nodes(db)
        if not any(n.singbox and n.singbox.tuic_enabled for n in nodes):
            raise HTTPException(
                status_code=400,
                detail="TUIC has no configured node on your server",
            )
        return
    if proxy_type == ProxyTypes.AnyTLS:
        nodes = crud.get_singbox_nodes(db)
        if not any(n.singbox and n.singbox.anytls_enabled for n in nodes):
            raise HTTPException(
                status_code=400,
                detail="AnyTLS has no configured node on your server",
            )
        return
    if not xray.config.inbounds_by_protocol.get(proxy_type):
        raise HTTPException(
            status_code=400,
            detail=f"Protocol {proxy_type} is disabled on your server",
        )


@router.post("/user", response_model=UserResponse, responses={400: responses._400, 409: responses._409})
def add_user(
    new_user: UserCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """
    Add a new user

    - **username**: 3 to 32 characters, can include a-z, 0-9, and underscores.
    - **status**: User's status, defaults to `active`. Special rules if `on_hold`.
    - **expire**: UTC timestamp for account expiration. Use `0` for unlimited.
    - **data_limit**: Max data usage in bytes (e.g., `1073741824` for 1GB). `0` means unlimited.
    - **data_limit_reset_strategy**: Defines how/if data limit resets. `no_reset` means it never resets.
    - **proxies**: Dictionary of protocol settings (e.g., `vmess`, `vless`).
    - **inbounds**: Dictionary of protocol tags to specify inbound connections.
    - **note**: Optional text field for additional user information or notes.
    - **on_hold_timeout**: UTC timestamp when `on_hold` status should start or end.
    - **on_hold_expire_duration**: Duration (in seconds) for how long the user should stay in `on_hold` status.
    - **next_plan**: Next user plan (resets after use).
    """

    # TODO expire should be datetime instead of timestamp

    for proxy_type in new_user.proxies:
        _ensure_protocol_enabled(proxy_type, db)

    from app.subscription.panel_balance import bind_user_to_panel, resolve_panel_for_create

    dbadmin = crud.get_admin(db, admin.username)
    try:
        panel_ep, balanced_username = resolve_panel_for_create(
            db, username=new_user.username, admin=dbadmin
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if balanced_username != new_user.username:
        new_user = new_user.model_copy(update={"username": balanced_username})

    from app.billing.reseller_tariffs import enforce_reseller_create_locks
    from app.billing.unlimited_create import (
        UnlimitedCreateChargeError,
        charge_unlimited_creates,
        prepare_unlimited_create_charge,
    )

    new_user, duration_days = enforce_reseller_create_locks(db, dbadmin, new_user)

    try:
        tariff_plan, unit_price = prepare_unlimited_create_charge(
            db,
            dbadmin,
            data_limit=new_user.data_limit,
            duration_days=duration_days,
            count=1,
        )
    except UnlimitedCreateChargeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    try:
        dbuser = crud.create_user(
            db,
            new_user,
            admin=dbadmin,
        )
    except ValueError as exc:
        if "limit reached" in str(exc).lower():
            raise HTTPException(status_code=403, detail=str(exc))
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")

    if tariff_plan is not None and unit_price > 0:
        charge_unlimited_creates(
            db,
            dbadmin,
            plan=tariff_plan,
            unit_price=unit_price,
            usernames=[dbuser.username],
        )
    elif tariff_plan is not None:
        from app.billing.reseller_tariffs import mark_user_tariff_charged

        mark_user_tariff_charged(dbuser, tariff_plan)
        db.commit()

    if panel_ep is not None:
        bind_user_to_panel(
            db,
            user_id=dbuser.id,
            username=dbuser.username,
            endpoint=panel_ep,
            source="auto-balance",
        )

    _enqueue_user_apply(db, dbuser, "add")
    user = _user_response(dbuser, share_links=True)
    report.user_created(user=user, user_id=dbuser.id, by=admin, user_admin=dbuser.admin)
    logger.info(
        'New user "%s" added (panel=%s)',
        dbuser.username,
        panel_ep.slug if panel_ep else "-",
    )
    return user


@router.post(
    "/user/from-template",
    response_model=UserResponse,
    responses={400: responses._400, 403: responses._403, 404: responses._404, 409: responses._409},
)
def add_user_from_template(
    body: UserFromTemplateCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Create a user from a saved template (prefix/suffix, limits, inbounds)."""
    db_tpl = crud.get_user_template(db, body.template_id)
    if db_tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    status = body.status
    if status is None and getattr(db_tpl, "default_status", None):
        status = UserStatusCreate(db_tpl.default_status.value)

    from app.subscription.panel_balance import bind_user_to_panel, resolve_panel_for_create

    try:
        new_user = _user_create_from_db_template(
            db_tpl, username=body.username.strip(), status=status
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    dbadmin = crud.get_admin(db, admin.username)
    try:
        panel_ep, balanced_username = resolve_panel_for_create(
            db, username=new_user.username, admin=dbadmin
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if balanced_username != new_user.username:
        new_user = new_user.model_copy(update={"username": balanced_username})

    for ptype in new_user.proxies:
        _ensure_protocol_enabled(ptype, db)

    from app.billing.reseller_tariffs import enforce_reseller_create_locks
    from app.billing.unlimited_create import (
        UnlimitedCreateChargeError,
        charge_unlimited_creates,
        prepare_unlimited_create_charge,
    )

    new_user, duration_days = enforce_reseller_create_locks(db, dbadmin, new_user)

    try:
        tariff_plan, unit_price = prepare_unlimited_create_charge(
            db,
            dbadmin,
            data_limit=new_user.data_limit,
            duration_days=duration_days,
            count=1,
        )
    except UnlimitedCreateChargeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    try:
        dbuser = crud.create_user(db, new_user, admin=dbadmin)
    except ValueError as exc:
        if "limit reached" in str(exc).lower():
            raise HTTPException(status_code=403, detail=str(exc))
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")

    if tariff_plan is not None and unit_price > 0:
        charge_unlimited_creates(
            db,
            dbadmin,
            plan=tariff_plan,
            unit_price=unit_price,
            usernames=[dbuser.username],
        )
    elif tariff_plan is not None:
        from app.billing.reseller_tariffs import mark_user_tariff_charged

        mark_user_tariff_charged(dbuser, tariff_plan)
        db.commit()

    if panel_ep is not None:
        bind_user_to_panel(
            db,
            user_id=dbuser.id,
            username=dbuser.username,
            endpoint=panel_ep,
            source="auto-balance",
        )

    _enqueue_user_apply(db, dbuser, "add")
    user = _user_response(dbuser, share_links=True)
    report.user_created(user=user, user_id=dbuser.id, by=admin, user_admin=dbuser.admin)
    logger.info(
        'New user "%s" added from template %s (panel=%s)',
        dbuser.username,
        body.template_id,
        panel_ep.slug if panel_ep else "-",
    )
    return user


@router.post(
    "/user/from-template/bulk",
    responses={400: responses._400, 403: responses._403, 404: responses._404},
)
def bulk_users_from_template(
    body: BulkFromTemplateCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Create many users from a template with random usernames (Marzban-style bulk)."""
    import secrets
    import string

    if body.count < 1 or body.count > 500:
        raise HTTPException(status_code=400, detail="count must be between 1 and 500")

    db_tpl = crud.get_user_template(db, body.template_id)
    if db_tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    status = body.status
    if getattr(db_tpl, "default_status", None):
        status = UserStatusCreate(db_tpl.default_status.value)

    prefix = body.username_prefix or db_tpl.username_prefix or ""
    suffix = body.username_suffix or db_tpl.username_suffix or ""
    dbadmin = crud.get_admin(db, admin.username)

    from app.billing.reseller_tariffs import (
        duration_days_from_expire,
        enforce_reseller_create_locks,
    )
    from app.billing.unlimited_create import (
        UnlimitedCreateChargeError,
        charge_unlimited_creates,
        prepare_unlimited_create_charge,
    )
    from app.subscription.panel_balance import bind_user_to_panel, resolve_panel_for_create

    # Probe duration from template expire so 30-day unlimited tariffs match.
    probe = _user_create_from_db_template(db_tpl, username="probeuserxx", status=status)
    duration_days = duration_days_from_expire(getattr(probe, "expire", None))
    try:
        tariff_plan, unit_price = prepare_unlimited_create_charge(
            db,
            dbadmin,
            data_limit=getattr(db_tpl, "data_limit", None),
            duration_days=duration_days,
            count=int(body.count),
        )
    except UnlimitedCreateChargeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    created: List[str] = []
    errors: List[str] = []
    alphabet = string.ascii_lowercase + string.digits

    for _ in range(body.count):
        core = "".join(secrets.choice(alphabet) for _ in range(8))
        # Pass core only — template may add its own prefix/suffix; we balance after.
        try:
            new_user = _user_create_from_db_template(
                db_tpl, username=f"{prefix}{core}{suffix}", status=status
            )
            panel_ep, balanced_username = resolve_panel_for_create(
                db, username=new_user.username, username_prefix=prefix or None
            )
            if balanced_username != new_user.username:
                new_user = new_user.model_copy(update={"username": balanced_username})
            new_user, _ = enforce_reseller_create_locks(db, dbadmin, new_user)
            for ptype in new_user.proxies:
                _ensure_protocol_enabled(ptype, db)
            dbuser = crud.create_user(db, new_user, admin=dbadmin)
            if panel_ep is not None:
                bind_user_to_panel(
                    db,
                    user_id=dbuser.id,
                    username=dbuser.username,
                    endpoint=panel_ep,
                    source="auto-balance",
                )
            created.append(dbuser.username)
        except IntegrityError:
            db.rollback()
            errors.append(f"{prefix}{core}{suffix}: already exists")
        except Exception as exc:
            errors.append(f"{prefix}{core}{suffix}: {exc}")

    if created and tariff_plan is not None and unit_price > 0 and dbadmin is not None:
        charge_unlimited_creates(
            db,
            dbadmin,
            plan=tariff_plan,
            unit_price=unit_price,
            usernames=created,
        )
    elif created and tariff_plan is not None:
        from app.billing.reseller_tariffs import mark_users_tariff_charged

        mark_users_tariff_charged(db, created, tariff_plan)

    if created:
        for uname in created:
            dbu = crud.get_user(db, uname)
            if dbu is not None:
                _enqueue_user_apply(db, dbu, "add")

    logger.info("Bulk template %s: created %s users", body.template_id, len(created))
    return {"created": len(created), "usernames": created, "errors": errors}


@router.post(
    "/users/bulk/inbounds/preview",
    responses={400: responses._400, 403: responses._403},
)
def bulk_inbound_preview(
    body: BulkInboundRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:read")),
):
    """Preview how many users would be affected by a bulk inbound add/remove."""
    from app.services.user_bulk import preview_bulk_inbound

    try:
        return preview_bulk_inbound(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/inbounds",
    responses={400: responses._400, 403: responses._403},
)
def bulk_inbound_apply(
    body: BulkInboundRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Add or remove an Xray inbound tag for many users in one fast operation."""
    from app.services.user_bulk import apply_bulk_inbound

    try:
        return apply_bulk_inbound(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/create",
    responses={400: responses._400, 403: responses._403},
)
def bulk_create_users(
    body: BulkUserCreateBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Create many users with shared limits, protocols, and inbounds (template optional)."""
    from app.services.user_bulk import bulk_create_users as run_bulk_create

    try:
        return run_bulk_create(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/extend",
    responses={400: responses._400, 403: responses._403},
)
def bulk_extend_users(
    body: BulkExtendRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Add days to expiry for many users at once."""
    from app.services.user_bulk import apply_bulk_extend

    try:
        return apply_bulk_extend(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/reset-usage",
    responses={400: responses._400, 403: responses._403},
)
def bulk_reset_users_usage(
    body: BulkResetUsageRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Reset data usage for many users at once."""
    from app.services.user_bulk import apply_bulk_reset_usage

    try:
        return apply_bulk_reset_usage(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/wireguard/preview",
    responses={400: responses._400, 403: responses._403},
)
def bulk_enable_wireguard_preview(
    body: BulkEnableWireGuardRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Preview enabling native WireGuard on many users (compat)."""
    from app.services.user_bulk import preview_bulk_enable_wireguard

    try:
        return preview_bulk_enable_wireguard(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/wireguard",
    responses={400: responses._400, 403: responses._403},
)
def bulk_enable_wireguard(
    body: BulkEnableWireGuardRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Enable native WireGuard / AmneziaWG for many users (compat)."""
    from app.services.user_bulk import apply_bulk_enable_wireguard

    _ensure_protocol_enabled(ProxyTypes.WireGuard, db)
    try:
        return apply_bulk_enable_wireguard(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/native-protocols/preview",
    responses={400: responses._400, 403: responses._403},
)
def bulk_native_protocol_preview(
    body: BulkNativeProtocolRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Preview enable/disable of a native node protocol on many users."""
    from app.services.user_bulk import preview_bulk_native_protocol

    try:
        return preview_bulk_native_protocol(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/native-protocols",
    responses={400: responses._400, 403: responses._403},
)
def bulk_native_protocol(
    body: BulkNativeProtocolRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Enable or disable WireGuard / Amnezia / Hysteria2 / TUIC / AnyTLS on many users."""
    from app.services.user_bulk import (
        BulkNativeAction,
        _native_proxy_type,
        apply_bulk_native_protocol,
    )

    if body.action == BulkNativeAction.enable:
        _ensure_protocol_enabled(_native_proxy_type(body.protocol), db)
    try:
        body.wait_sync = True
        return apply_bulk_native_protocol(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/status",
    responses={400: responses._400, 403: responses._403},
)
def bulk_status_users(
    body: BulkStatusRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Enable or disable many users at once."""
    from app.services.user_bulk import apply_bulk_status

    try:
        return apply_bulk_status(db, body, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/users/bulk/delete",
    responses={400: responses._400, 403: responses._403, 409: responses._409},
)
def bulk_delete_users(
    body: BulkDeleteRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Delete many users at once (selected / filtered by status / all).

    Small selected deletes stay synchronous; large filtered/all scopes run as a
    background job (returns ``{job_id, async: true}``) so reverse-proxy
    timeouts cannot abort the request while thousands of rows are removed.
    Poll ``GET /users/bulk/delete/status/{job_id}`` for progress.
    """
    import threading

    from app.db import GetDB
    from app.services import bulk_delete_jobs
    from app.services.user_bulk import _iter_delete_targets, apply_bulk_delete

    try:
        targets = _iter_delete_targets(
            db,
            admin=admin,
            scope=body.scope,
            usernames=body.usernames,
            statuses=body.statuses,
            filters=body.filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    count = len(targets)
    # Bulk SQL delete is fast now — keep larger selected batches synchronous.
    sync_ok = body.scope.value == "selected" and count <= 500
    if sync_ok or count == 0:
        try:
            return apply_bulk_delete(db, body, admin=admin)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if bulk_delete_jobs.active_job() is not None:
        raise HTTPException(
            status_code=409,
            detail="A bulk delete is already running. Wait for it to finish.",
        )

    # Capture identifiers for the worker — don't hand the request Session across threads.
    admin_username = admin.username if admin and not admin.is_sudo else None
    payload = body.model_dump()
    job = bulk_delete_jobs.create(total=count)

    def _worker(job_id: str) -> None:
        def progress(processed_delta: int = 0, deleted_delta: int = 0) -> None:
            bulk_delete_jobs.bump(
                job_id, processed_delta=processed_delta, deleted_delta=deleted_delta
            )

        try:
            with GetDB() as wdb:
                worker_admin = None
                if admin_username:
                    worker_admin = crud.get_admin(wdb, admin_username)
                req = BulkDeleteRequest(**payload)
                result = apply_bulk_delete(
                    wdb, req, admin=worker_admin, progress_cb=progress
                )
            bulk_delete_jobs.finish(job_id, state="done", deleted=result.deleted)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Background bulk delete %s failed", job_id)
            bulk_delete_jobs.finish(job_id, state="error", error=str(exc))

    threading.Thread(
        target=_worker,
        args=(job.id,),
        name=f"bulk-delete-{job.id[:8]}",
        daemon=True,
    ).start()
    return {"job_id": job.id, "state": job.state, "async": True, "total": count}


@router.get("/users/bulk/delete/status/{job_id}")
def bulk_delete_status(
    job_id: str,
    _: Admin = Depends(require_permission("users:write")),
):
    from app.services import bulk_delete_jobs

    job = bulk_delete_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired bulk-delete job")
    return job.to_dict()


@router.get("/user/{username}", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def get_user(dbuser: User = Depends(get_validated_user)):
    """Get user information.

    The admin drawer renders every share config from ``links``/``link_items``.
    The default ``UserResponse`` validator only fills Xray URIs (vless/vmess/
    trojan/ss); sing-box (hysteria2/tuic/anytls) and WireGuard live on separate
    node-bound builders, so enrich the payload here to expose all protocols.
    """
    return _user_response(dbuser, share_links=True)


@router.put("/user/{username}", response_model=UserResponse, responses={400: responses._400, 403: responses._403, 404: responses._404})
def modify_user(
    modified_user: UserModify,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """
    Modify an existing user

    - **username**: Cannot be changed. Used to identify the user.
    - **status**: User's new status. Can be 'active', 'disabled', 'on_hold', 'limited', or 'expired'.
    - **expire**: UTC timestamp for new account expiration. Set to `0` for unlimited, `null` for no change.
    - **data_limit**: New max data usage in bytes (e.g., `1073741824` for 1GB). Set to `0` for unlimited, `null` for no change.
    - **data_limit_reset_strategy**: New strategy for data limit reset. Options include 'daily', 'weekly', 'monthly', or 'no_reset'.
    - **proxies**: Dictionary of new protocol settings (e.g., `vmess`, `vless`). Empty dictionary means no change.
    - **inbounds**: Dictionary of new protocol tags to specify inbound connections. Empty dictionary means no change.
    - **note**: New optional text for additional user information or notes. `null` means no change.
    - **on_hold_timeout**: New UTC timestamp for when `on_hold` status should start or end. Only applicable if status is changed to 'on_hold'.
    - **on_hold_expire_duration**: New duration (in seconds) for how long the user should stay in `on_hold` status. Only applicable if status is changed to 'on_hold'.
    - **next_plan**: Next user plan (resets after use).

    Note: Fields set to `null` or omitted will not be modified.
    """

    for proxy_type in modified_user.proxies:
        _ensure_protocol_enabled(proxy_type, db)

    # Reseller cannot override master-locked device/speed from wholesale tariff.
    # Also debit wallet when edit upgrades/renews into a matching tariff.
    modify_tariff = None
    modify_unit_price = 0
    if not admin.is_sudo:
        from app.billing.reseller_tariffs import (
            ResellerTariffError,
            apply_locked_limits_to_user_payload,
            duration_days_from_expire,
            prepare_reseller_modify_charge,
            resolve_locked_limits_for_admin,
        )

        dbadmin = crud.get_admin(db, admin.username)
        next_data_limit = (
            modified_user.data_limit
            if "data_limit" in modified_user.model_fields_set
            else dbuser.data_limit
        )
        next_expire = (
            modified_user.expire
            if "expire" in modified_user.model_fields_set
            else dbuser.expire
        )
        locks = resolve_locked_limits_for_admin(
            db,
            dbadmin,
            data_limit=next_data_limit,
            duration_days=duration_days_from_expire(next_expire),
            expire=next_expire,
        )
        if locks:
            modified_user = apply_locked_limits_to_user_payload(modified_user, locks)

        try:
            modify_tariff, modify_unit_price = prepare_reseller_modify_charge(
                db,
                dbadmin,
                dbuser,
                next_data_limit=next_data_limit,
                next_expire=next_expire,
            )
        except ResellerTariffError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    old_status = dbuser.status
    dbuser = crud.update_user(db, dbuser, modified_user)

    if modify_tariff is not None:
        from app.billing.reseller_tariffs import (
            charge_reseller_tariff,
            mark_user_tariff_charged,
        )

        if modify_unit_price > 0:
            dbadmin = crud.get_admin(db, admin.username)
            charge_reseller_tariff(
                db,
                dbadmin,
                tariff=modify_tariff,
                unit_price=modify_unit_price,
                usernames=[dbuser.username],
                event="modify",
            )
        mark_user_tariff_charged(dbuser, modify_tariff)
        db.commit()

    status_changed = dbuser.status != old_status
    if dbuser.status in [UserStatus.active, UserStatus.on_hold]:
        _enqueue_user_apply(
            db,
            dbuser,
            "add" if status_changed else "protocol_change",
        )
    else:
        _enqueue_user_apply(db, dbuser, "disable")

    user = _user_response(dbuser, share_links=True)

    bg.add_task(report.user_updated, user=user, user_admin=dbuser.admin, by=admin)

    logger.info(f'User "{user.username}" modified')

    if user.status != old_status:
        bg.add_task(
            report.status_change,
            username=user.username,
            status=user.status,
            user=user,
            user_admin=dbuser.admin,
            by=admin,
        )
        logger.info(
            f'User "{dbuser.username}" status changed from {old_status} to {user.status}'
        )

    return user


@router.delete("/user/{username}", responses={403: responses._403, 404: responses._404})
def remove_user(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Remove a user"""
    username = dbuser.username
    user_admin = Admin.model_validate(dbuser.admin) if dbuser.admin else None
    from app.sync.outbox import schedule_user_sync, snapshot_user

    schedule_user_sync(db, dbuser, "delete", payload=snapshot_user(dbuser))
    crud.remove_user(db, dbuser)

    bg.add_task(
        report.user_deleted, username=username, user_admin=user_admin, by=admin
    )

    logger.info(f'User "{username}" deleted')
    return {"detail": "User successfully deleted"}


@router.post("/user/{username}/reset", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def reset_user_data_usage(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Reset user data usage"""
    dbuser = crud.reset_user_data_usage(db=db, dbuser=dbuser)
    if dbuser.status in (UserStatus.active, UserStatus.on_hold):
        _enqueue_user_apply(db, dbuser, "quota_cap")

    user = _user_response(dbuser, share_links=True)
    bg.add_task(
        report.user_data_usage_reset, user=user, user_admin=dbuser.admin, by=admin
    )

    logger.info(f'User "{dbuser.username}"\'s usage was reset')
    return user


@router.post("/user/{username}/rotate_sub", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def rotate_user_subscription_link(
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Rotate subscription link only (sub_token); proxy UUIDs stay unchanged."""
    dbuser = crud.rotate_user_sub_link(db=db, dbuser=dbuser)
    user = _user_response(dbuser)
    logger.info(f'User "{dbuser.username}" subscription link rotated')
    return user


@router.post("/user/{username}/revoke_sub", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def revoke_user_subscription(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Revoke users subscription (Subscription link and proxies)"""
    dbuser = crud.revoke_user_sub(db=db, dbuser=dbuser)

    if dbuser.status in [UserStatus.active, UserStatus.on_hold]:
        _enqueue_user_apply(db, dbuser, "protocol_change")
    user = _user_response(dbuser)
    bg.add_task(
        report.user_subscription_revoked, user=user, user_admin=dbuser.admin, by=admin
    )

    logger.info(f'User "{dbuser.username}" subscription revoked')

    return user


@router.get("/users", response_model=UsersResponse, responses={400: responses._400, 403: responses._403, 404: responses._404})
def get_users(
    offset: int = None,
    limit: int = None,
    username: List[str] = Query(None),
    search: Union[str, None] = None,
    owner: Union[List[str], None] = Query(None, alias="admin"),
    status: UserStatus = None,
    protocol: str = None,
    inbound_tag: str = None,
    source_slug: str = None,
    expiring_within_days: int = None,
    near_limit_percent: int = None,
    sort: str = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:read")),
):
    """Get all users"""
    if sort is not None:
        opts = sort.strip(",").split(",")
        sort = []
        for opt in opts:
            try:
                sort.append(crud.UsersSortingOptions[opt])
            except KeyError:
                raise HTTPException(
                    status_code=400, detail=f'"{opt}" is not a valid sort option'
                )

    users, count = crud.get_users(
        db=db,
        offset=offset,
        limit=limit,
        search=search,
        usernames=username,
        status=status,
        sort=sort,
        admins=owner if admin.is_sudo else [admin.username],
        protocol=protocol,
        inbound_tag=inbound_tag,
        source_slug=source_slug,
        expiring_within_days=expiring_within_days,
        near_limit_percent=near_limit_percent,
        return_with_count=True,
    )

    return {"users": users, "total": count}


@router.get("/users/stat-usernames", responses={403: responses._403})
def get_stat_usernames(
    category: str,
    limit: int = 15,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:read")),
):
    """Usernames behind a dashboard stat tile (for the hover preview).

    ``category`` ∈ {total, online, active, disabled, expired, limited, on_hold}.
    Scoped to the caller's own users unless they are a sudo admin.
    """
    dbadmin = crud.get_admin(db, admin.username)
    scope = dbadmin if not admin.is_sudo else None
    usernames, total = crud.list_usernames_by_stat(
        db, category, admin=scope, limit=max(1, min(limit, 200))
    )
    return {"category": category, "usernames": usernames, "total": total}


@router.get(
    "/users/filter-options",
    responses={403: responses._403},
)
def get_users_filter_options(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:read")),
):
    """Source servers, inbound tags, and protocols for the users list filters."""
    dbadmin = crud.get_admin(db, admin.username)
    return crud.get_user_list_filter_options(db, admin=dbadmin)


@router.post("/users/reset", responses={403: responses._403, 404: responses._404})
def reset_users_data_usage(
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Reset all users data usage"""
    dbadmin = crud.get_admin(db, admin.username)
    crud.reset_all_users_data_usage(db=db, admin=dbadmin)
    # Limited accounts become active again; apply on the worker, never here.
    from app.sync.wake import request_fleet_resync

    request_fleet_resync()
    return {"detail": "Users successfully reset."}


@router.get("/user/{username}/usage", response_model=UserUsagesResponse, responses={403: responses._403, 404: responses._404})
def get_user_usage(
    dbuser: User = Depends(get_validated_user),
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
):
    """Get users usage"""
    start, end = validate_dates(start, end)

    usages = crud.get_user_usages(db, dbuser, start, end)

    return {"usages": usages, "username": dbuser.username}


class ApplyPlanBody(BaseModel):
    plan_id: int


@router.post("/user/{username}/apply-plan", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def apply_plan_to_user_endpoint(
    body: ApplyPlanBody,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Sell a commercial plan to a user (debits reseller wallet, renews immediately)."""
    from app import billing, feature_flags
    from app.portal import apply_plan_to_user, create_user_order, mark_order_applied
    from app.tenant.plan_ops import assert_plan_accessible, assert_plan_for_user

    if not feature_flags.is_enabled("billing"):
        raise HTTPException(status_code=404, detail="Billing is disabled")

    plan = crud.get_plan_by_id(db, body.plan_id)
    if not plan or not plan.enabled:
        raise HTTPException(status_code=404, detail="Plan not found")

    dbrow = crud.get_user(db, dbuser.username)
    if not dbrow or not dbrow.admin_id:
        raise HTTPException(status_code=400, detail="User has no owning reseller")

    assert_plan_accessible(db, admin, plan)
    assert_plan_for_user(db, dbrow.admin_id, plan)

    price = int(plan.price or 0)
    if price > 0:
        wallet = billing.get_or_create_wallet(db, dbrow.admin_id)
        if wallet.balance < price:
            raise HTTPException(
                status_code=402,
                detail="Insufficient wallet balance — top up before selling this plan",
            )
        billing.add_transaction(
            db,
            dbrow.admin_id,
            -price,
            type="plan_sale",
            description=f"Plan sale for {dbrow.username} — {plan.name}",
            reference=f"user:{dbrow.id}:plan:{plan.id}",
        )

    order = create_user_order(db, dbrow, plan, status="paid")
    dbrow = apply_plan_to_user(db, dbrow, plan)
    mark_order_applied(db, order)

    if dbrow.status in (UserStatus.active, UserStatus.on_hold):
        _enqueue_user_apply(db, dbrow, "add")

    logger.info(f'User "{dbrow.username}" renewed via plan "{plan.name}" by {admin.username}')
    return _user_response(dbrow)


@router.post("/user/{username}/active-next", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def active_next_plan(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_validated_user),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Reset user by next plan"""
    dbuser = crud.reset_user_by_next(db=db, dbuser=dbuser)

    # crud.reset_user_by_next returns None only when the user had no next plan.
    # On success it returns the user with next_plan already cleared, so we must
    # NOT treat a null next_plan as failure here.
    if dbuser is None:
        raise HTTPException(
            status_code=404,
            detail="User doesn't have next plan",
        )

    if dbuser.status in [UserStatus.active, UserStatus.on_hold]:
        _enqueue_user_apply(db, dbuser, "add")

    user = _user_response(dbuser)
    bg.add_task(
        report.user_data_reset_by_next, user=user, user_admin=dbuser.admin,
    )

    logger.info(f'User "{dbuser.username}"\'s usage was reset by next plan')
    return user


@router.get("/users/usage", response_model=UsersUsagesResponse)
def get_users_usage(
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
    owner: Union[List[str], None] = Query(None, alias="admin"),
    admin: Admin = Depends(require_permission("users:read")),
):
    """Get all users usage"""
    start, end = validate_dates(start, end)

    usages = crud.get_all_users_usages(
        db=db, start=start, end=end, admin=owner if admin.is_sudo else [admin.username]
    )

    return {"usages": usages}


@router.put("/user/{username}/set-owner", response_model=UserResponse)
def set_owner(
    admin_username: str,
    dbuser: User = Depends(get_validated_user),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Set a new owner (admin) for a user."""
    new_admin = crud.get_admin(db, username=admin_username)
    if not new_admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    dbuser = crud.set_owner(db, dbuser, new_admin)
    user = _user_response(dbuser)

    logger.info(f'{user.username}"owner successfully set to{admin.username}')

    return user


@router.get("/users/expired", response_model=List[str])
def get_expired_users(
    expired_after: Optional[datetime] = Query(None, example="2024-01-01T00:00:00"),
    expired_before: Optional[datetime] = Query(None, example="2024-01-31T23:59:59"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:read")),
):
    """
    Get users who have expired within the specified date range.

    - **expired_after** UTC datetime (optional)
    - **expired_before** UTC datetime (optional)
    - At least one of expired_after or expired_before must be provided for filtering
    - If both are omitted, returns all expired users
    """

    expired_after, expired_before = validate_dates(expired_after, expired_before)

    expired_users = get_expired_users_list(db, admin, expired_after, expired_before)
    return [u.username for u in expired_users]


@router.delete("/users/expired", response_model=List[str])
def delete_expired_users(
    bg: BackgroundTasks,
    expired_after: Optional[datetime] = Query(None, example="2024-01-01T00:00:00"),
    expired_before: Optional[datetime] = Query(None, example="2024-01-31T23:59:59"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """
    Delete users who have expired within the specified date range.

    - **expired_after** UTC datetime (optional)
    - **expired_before** UTC datetime (optional)
    - At least one of expired_after or expired_before must be provided
    """
    expired_after, expired_before = validate_dates(expired_after, expired_before)

    expired_users = get_expired_users_list(db, admin, expired_after, expired_before)
    removed_users = [u.username for u in expired_users]

    if not removed_users:
        raise HTTPException(
            status_code=404, detail="No expired users found in the specified date range"
        )

    crud.remove_users(db, expired_users)

    for removed_user in removed_users:
        logger.info(f'User "{removed_user}" deleted')
        bg.add_task(
            report.user_deleted,
            username=removed_user,
            user_admin=next(
                (u.admin for u in expired_users if u.username == removed_user), None
            ),
            by=admin,
        )

    return removed_users
