import hmac
from typing import Optional, Union
from app.models.admin import AdminInDB, AdminValidationResult, Admin
from app.db.models import User
from app.models.user import UserStatus
from app.db import Session, crud, get_db
from config import SUDOERS, SUDO_PASSWORD_HASH, SUDO_USERNAME
from fastapi import Depends, HTTPException, Request
from datetime import datetime, timezone, timedelta
import re

from app.utils.jwt import get_subscription_payload
from app.rbac import require_permission
from app.subscription.endpoint_resolver import (
    build_subscription_context,
    panel_endpoint_ids_for_subscription,
    SubscriptionRequestContext,
)


def validate_admin(db: Session, username: str, password: str) -> Optional[AdminValidationResult]:
    """Validate admin credentials with environment variables or database."""
    if SUDO_USERNAME and username == SUDO_USERNAME and SUDO_PASSWORD_HASH:
        from passlib.hash import bcrypt
        try:
            if bcrypt.verify(password or "", SUDO_PASSWORD_HASH):
                return AdminValidationResult(username=username, is_sudo=True)
        except ValueError:
            pass

    expected = SUDOERS.get(username)
    if expected is not None and hmac.compare_digest(expected, password or ""):
        return AdminValidationResult(username=username, is_sudo=True)

    dbadmin = crud.get_admin(db, username)
    if dbadmin and AdminInDB.model_validate(dbadmin).verify_password(password):
        return AdminValidationResult(username=dbadmin.username, is_sudo=dbadmin.is_sudo)

    return None


def get_admin_by_username(username: str, db: Session = Depends(get_db)):
    """Fetch an admin by username from the database."""
    dbadmin = crud.get_admin(db, username)
    if not dbadmin:
        raise HTTPException(status_code=404, detail="Admin not found")
    return dbadmin


def get_dbnode(node_id: int, db: Session = Depends(get_db)):
    """Fetch a node by its ID from the database, raising a 404 error if not found."""
    dbnode = crud.get_node_by_id(db, node_id)
    if not dbnode:
        raise HTTPException(status_code=404, detail="Node not found")
    return dbnode


def get_scoped_node(
    dbnode=Depends(get_dbnode),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("nodes:read")),
):
    """Return a node only if the current admin may access it."""
    from app.tenant.reseller_ops import assert_owns_node
    assert_owns_node(db, admin, dbnode)
    return dbnode


def validate_dates(start: Optional[Union[str, datetime]], end: Optional[Union[str, datetime]]) -> (datetime, datetime):
    """Validate if start and end dates are correct and if end is after start."""
    try:
        if start:
            start_date = start if isinstance(start, datetime) else datetime.fromisoformat(
                start).astimezone(timezone.utc)
        else:
            start_date = datetime.now(timezone.utc) - timedelta(days=30)
        if end:
            end_date = end if isinstance(end, datetime) else datetime.fromisoformat(end).astimezone(timezone.utc)
            if start_date and end_date < start_date:
                raise HTTPException(status_code=400, detail="Start date must be before end date")
        else:
            end_date = datetime.now(timezone.utc)

        return start_date, end_date
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date range or format")


def get_user_template(template_id: int, db: Session = Depends(get_db)):
    """Fetch a User Template by its ID, raise 404 if not found."""
    dbuser_template = crud.get_user_template(db, template_id)
    if not dbuser_template:
        raise HTTPException(status_code=404, detail="User Template not found")
    return dbuser_template


def get_subscription_context(
    request: Request,
    db: Session = Depends(get_db),
) -> SubscriptionRequestContext:
    ctx = build_subscription_context(request, db)
    request.state.subscription_context = ctx
    return ctx


def resolve_sub_ctx(
    sub_ctx: object, request: Request, db: Session
) -> SubscriptionRequestContext:
    """Return the injected context, or build one when the handler is called
    directly (e.g. from unit tests / internal callers) so FastAPI's ``Depends``
    default marker never leaks into the body."""
    if isinstance(sub_ctx, SubscriptionRequestContext):
        return sub_ctx
    if isinstance(request, Request) and isinstance(db, Session):
        return build_subscription_context(request, db)
    # No usable request/session (direct call, or a blocked-export path that
    # never touches the DB): fall back to the global default endpoint.
    return SubscriptionRequestContext(
        endpoint=None, path_prefix="", inbound_filter=None, format_default=None
    )


def get_validated_sub(
        token: str,
        request: Request,
        db: Session = Depends(get_db),
        sub_ctx: SubscriptionRequestContext = Depends(get_subscription_context),
) -> User:
    sub_ctx = resolve_sub_ctx(sub_ctx, request, db)
    endpoint_id = sub_ctx.endpoint.id if sub_ctx.endpoint else None

    # Independent sub_token (Marzban-style): 32-char hex, no JWT parsing.
    if re.fullmatch(r"[0-9a-fA-F]{32}", token or ""):
        dbuser = crud.get_user_by_sub_token(db, token.lower())
        if dbuser:
            if dbuser.sub_revoked_at:
                raise HTTPException(status_code=404, detail="Not Found")
            return dbuser
        raise HTTPException(status_code=404, detail="Not Found")

    # Legacy 3x-ui subId and other alias tokens.
    alias = crud.get_subscription_token_alias(db, token, endpoint_id=endpoint_id)
    if not alias and sub_ctx.endpoint:
        for panel_id in panel_endpoint_ids_for_subscription(db, sub_ctx.endpoint):
            alias = crud.get_subscription_token_alias(db, token, endpoint_id=panel_id)
            if alias:
                break
    # Reseller branding domains (slug reseller-*) re-host panel aliases under a
    # custom host — accept the token from any endpoint when the user belongs
    # to that reseller tenant.
    if not alias and sub_ctx.endpoint:
        slug = (sub_ctx.endpoint.slug or "").strip()
        if slug.startswith("reseller-"):
            candidate = crud.get_subscription_token_alias_any_endpoint(db, token)
            if candidate:
                from app.db.models import Admin, User

                dbuser = db.query(User).filter(User.id == candidate.user_id).first()
                if dbuser and dbuser.admin_id:
                    admin = db.query(Admin).filter(Admin.id == dbuser.admin_id).first()
                    try:
                        expected_tid = int(slug.split("-", 1)[1])
                    except (IndexError, ValueError):
                        expected_tid = None
                    if (
                        admin
                        and admin.tenant_id is not None
                        and expected_tid is not None
                        and int(admin.tenant_id) == expected_tid
                    ):
                        alias = candidate
    if alias:
        from app.db.models import User
        dbuser = db.query(User).filter(User.id == alias.user_id).first()
        if dbuser:
            if dbuser.sub_revoked_at:
                raise HTTPException(status_code=404, detail="Not Found")
            return dbuser

    sub = get_subscription_payload(token)
    if not sub:
        raise HTTPException(status_code=404, detail="Not Found")

    dbuser = crud.get_user(db, sub['username'])
    if not dbuser:
        raise HTTPException(status_code=404, detail="Not Found")

    sub_created = sub.get("created_at")
    token_ts = int(sub_created.timestamp()) if sub_created else 0

    if token_ts > 0:
        # Legacy time-based tokens: reject if user was created after the token was issued.
        user_ts = int(dbuser.created_at.replace(tzinfo=None).timestamp())
        if user_ts > token_ts:
            raise HTTPException(status_code=404, detail="Not Found")
        if dbuser.sub_revoked_at and dbuser.sub_revoked_at > sub_created:
            raise HTTPException(status_code=404, detail="Not Found")
    elif dbuser.sub_revoked_at:
        # Stable per-user token (epoch 0): invalid only when subscription was revoked.
        raise HTTPException(status_code=404, detail="Not Found")

    return dbuser


def get_validated_user(
        username: str,
        admin: Admin = Depends(require_permission("users:read")),
        db: Session = Depends(get_db)
) -> User:
    dbuser = crud.get_user(db, username)
    if not dbuser:
        raise HTTPException(status_code=404, detail="User not found")

    if not (admin.is_sudo or (dbuser.admin and dbuser.admin.username == admin.username)):
        raise HTTPException(status_code=403, detail="You're not allowed")

    return dbuser


def get_expired_users_list(db: Session, admin: Admin, expired_after: Optional[datetime] = None,
                           expired_before: Optional[datetime] = None):
    expired_before = expired_before or datetime.now(timezone.utc)
    expired_after = expired_after or datetime.min.replace(tzinfo=timezone.utc)

    dbadmin = crud.get_admin(db, admin.username)
    dbusers = crud.get_users(
        db=db,
        status=[UserStatus.expired, UserStatus.limited],
        admin=dbadmin if not admin.is_sudo else None
    )

    return [
        u for u in dbusers
        if u.expire and expired_after.timestamp() <= u.expire <= expired_before.timestamp()
    ]
