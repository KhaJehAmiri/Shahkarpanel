from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app import xray
from app.db import Session, crud, get_db
from app.dependencies import get_admin_by_username, validate_admin
from app.login_limit import (
    clear_login_failures,
    enforce_admin_ip_allowlist,
    enforce_login_rate_limit,
    record_login_failure,
)
from app.models.admin import Admin, AdminCreate, AdminModify, AdminRefreshBody, Token
from app.utils import report, responses
from app.utils.jwt import admin_token_bundle, get_admin_refresh_payload
from config import (
    LOGIN_MAX_ATTEMPTS,
    LOGIN_MAX_WINDOW_SECONDS,
    LOGIN_NOTIFY_WHITE_LIST,
    OIDC_CLIENT_ID,
    OIDC_ISSUER,
    OIDC_REDIRECT_URI,
    SUDO_USERNAME,
)

router = APIRouter(tags=["Admin"], prefix="/api", responses={401: responses._401})


def get_client_ip(request: Request) -> str:
    """Extract the client's IP address from the request headers or client."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "Unknown"


@router.post("/admin/token", response_model=Token)
async def admin_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate an admin and issue a token."""
    enforce_login_rate_limit(
        request,
        max_attempts=LOGIN_MAX_ATTEMPTS,
        window_seconds=LOGIN_MAX_WINDOW_SECONDS,
    )
    client_ip = get_client_ip(request)
    enforce_admin_ip_allowlist(client_ip)

    dbadmin = validate_admin(db, form_data.username, form_data.password)
    if not dbadmin:
        record_login_failure(request, window_seconds=LOGIN_MAX_WINDOW_SECONDS)
        report.login(form_data.username, "🔒", client_ip, False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Opt-in TOTP 2FA: only enforced when this admin has enrolled a secret.
    # Admins without a secret log in exactly as before (no lockout risk).
    stored = crud.get_admin(db, form_data.username)
    if stored is not None and getattr(stored, "totp_secret", None):
        from app.utils import totp

        form = await request.form()
        otp = (form.get("otp") or form.get("totp") or form.get("code") or "").strip()
        if not otp:
            record_login_failure(request, window_seconds=LOGIN_MAX_WINDOW_SECONDS)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Two-factor authentication code required",
                headers={"WWW-Authenticate": "Bearer", "X-2FA-Required": "true"},
            )
        if not totp.verify(stored.totp_secret, otp):
            record_login_failure(request, window_seconds=LOGIN_MAX_WINDOW_SECONDS)
            report.login(form_data.username, "🔒", client_ip, False)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid two-factor authentication code",
                headers={"WWW-Authenticate": "Bearer", "X-2FA-Required": "true"},
            )

    clear_login_failures(request)
    if client_ip not in LOGIN_NOTIFY_WHITE_LIST:
        report.login(form_data.username, "🔒", client_ip, True)

    from app.utils.admin_sessions import record_login

    record_login(form_data.username, ip=client_ip, is_sudo=dbadmin.is_sudo)

    return Token(**admin_token_bundle(form_data.username, dbadmin.is_sudo))


@router.post("/admin/refresh", response_model=Token)
def admin_refresh(body: AdminRefreshBody, db: Session = Depends(get_db)):
    """Exchange a valid admin refresh token for a fresh access token (L6)."""
    payload = get_admin_refresh_payload(body.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = payload["username"]
    dbadmin = crud.get_admin(db, username)
    if dbadmin is not None:
        is_sudo = bool(dbadmin.is_sudo)
    elif username == SUDO_USERNAME and payload.get("is_sudo"):
        is_sudo = True
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from app.utils.jwt import app_access_token_expires_in, create_admin_token

    return Token(
        access_token=create_admin_token(username, is_sudo),
        expires_in=app_access_token_expires_in(),
    )


def _require_db_admin(db: Session, admin: Admin):
    """Resolve the DB row for 2FA operations (env-only sudo admins can't enroll)."""
    stored = crud.get_admin(db, admin.username)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication requires a database-backed admin account.",
        )
    return stored


@router.get("/admin/2fa", responses={401: responses._401})
def two_factor_status(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
) -> dict:
    """Report whether the current admin has TOTP 2FA enabled."""
    stored = crud.get_admin(db, admin.username)
    return {"enabled": bool(stored is not None and getattr(stored, "totp_secret", None))}


@router.post("/admin/2fa/setup", responses={401: responses._401})
def two_factor_setup(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
) -> dict:
    """Generate a fresh TOTP secret + provisioning URI (not yet enabled).

    The caller must confirm a valid code via ``/admin/2fa/enable`` before 2FA is
    activated, so a mistyped/unscanned secret can never lock the admin out.
    """
    from app.utils import totp

    _require_db_admin(db, admin)
    secret = totp.generate_secret()
    return {
        "secret": secret,
        "provisioning_uri": totp.provisioning_uri(secret, admin.username),
    }


@router.post("/admin/2fa/enable", responses={401: responses._401})
def two_factor_enable(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
) -> dict:
    """Activate 2FA after verifying a code against the setup secret."""
    from app.utils import totp

    stored = _require_db_admin(db, admin)
    secret = str((payload or {}).get("secret") or "").strip()
    code = str((payload or {}).get("code") or (payload or {}).get("otp") or "").strip()
    if not secret or not code:
        raise HTTPException(status_code=400, detail="secret and code are required")
    if not totp.verify(secret, code):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    crud.set_admin_totp_secret(db, stored, secret)
    return {"enabled": True}


@router.post("/admin/2fa/disable", responses={401: responses._401})
def two_factor_disable(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
) -> dict:
    """Disable 2FA. Requires a valid current code to prevent hijacked-session abuse."""
    from app.utils import totp

    stored = _require_db_admin(db, admin)
    if not getattr(stored, "totp_secret", None):
        return {"enabled": False}
    code = str((payload or {}).get("code") or (payload or {}).get("otp") or "").strip()
    if not totp.verify(stored.totp_secret, code):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    crud.set_admin_totp_secret(db, stored, None)
    return {"enabled": False}


@router.post(
    "/admin",
    response_model=Admin,
    responses={403: responses._403, 409: responses._409},
)
def create_admin(
    new_admin: AdminCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Create a new admin if the current admin has sudo privileges."""
    try:
        dbadmin = crud.create_admin(db, new_admin)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Admin already exists")

    return dbadmin


@router.put(
    "/admin/{username}",
    response_model=Admin,
    responses={403: responses._403},
)
def modify_admin(
    modified_admin: AdminModify,
    dbadmin: Admin = Depends(get_admin_by_username),
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Modify an existing admin's details."""
    if (dbadmin.username != current_admin.username) and dbadmin.is_sudo:
        raise HTTPException(
            status_code=403,
            detail="You're not allowed to edit another sudoer's account. Use shahkar-cli instead.",
        )

    updated_admin = crud.update_admin(db, dbadmin, modified_admin)

    return updated_admin


@router.delete(
    "/admin/{username}",
    responses={403: responses._403},
)
def remove_admin(
    dbadmin: Admin = Depends(get_admin_by_username),
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Remove an admin from the database."""
    if dbadmin.is_sudo:
        raise HTTPException(
            status_code=403,
            detail="You're not allowed to delete sudo accounts. Use shahkar-cli instead.",
        )

    crud.remove_admin(db, dbadmin)
    return {"detail": "Admin removed successfully"}


@router.get("/admin")
def get_current_admin(admin: Admin = Depends(Admin.get_current)):
    """Retrieve the current authenticated admin."""
    from app.rbac import PERMISSIONS, role_permissions

    data = admin.model_dump()
    if admin.is_sudo:
        data["permissions"] = sorted(PERMISSIONS)
    else:
        data["permissions"] = sorted(role_permissions(admin.role or "reseller"))
    return data


class _PasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


class _UsernameChangeBody(BaseModel):
    new_username: str
    current_password: str


@router.put("/admin/me/password")
def change_my_password(
    body: _PasswordChangeBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Reseller/admin self-service password change (requires current password)."""
    from datetime import datetime

    from app.models.admin import pwd_context

    new_password = (body.new_password or "").strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="new_password must be at least 6 characters")
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        raise HTTPException(
            status_code=400,
            detail="Password change requires a database-backed admin",
        )
    if not pwd_context.verify(body.current_password or "", dbadmin.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    dbadmin.hashed_password = pwd_context.hash(new_password)
    dbadmin.password_reset_at = datetime.utcnow()
    db.commit()
    return {"detail": "Password updated"}


@router.put("/admin/me/username")
def change_my_username(
    body: _UsernameChangeBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Reseller self-service username change. Forces re-login (JWT is username-bound)."""
    import re
    from datetime import datetime

    from app.models.admin import pwd_context
    from app.utils.admin_sessions import revoke_user_sessions

    if admin.is_sudo:
        raise HTTPException(status_code=400, detail="Sudo username cannot be changed here")
    new_username = (body.new_username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,32}", new_username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3–32 chars: lowercase letters, digits, underscore",
        )
    if new_username == admin.username.lower():
        return {"detail": "Username unchanged", "username": admin.username}
    dbadmin = crud.get_admin(db, admin.username)
    if dbadmin is None:
        raise HTTPException(
            status_code=400,
            detail="Username change requires a database-backed admin",
        )
    if not pwd_context.verify(body.current_password or "", dbadmin.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if crud.get_admin(db, new_username) is not None:
        raise HTTPException(status_code=409, detail="Username already taken")
    old = dbadmin.username
    dbadmin.username = new_username
    dbadmin.password_reset_at = datetime.utcnow()
    db.commit()
    try:
        revoke_user_sessions(old)
    except Exception:
        pass
    return {"detail": "Username updated — please sign in again", "username": new_username}


@router.get(
    "/admins",
    response_model=List[Admin],
    responses={403: responses._403},
)
def get_admins(
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    username: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Fetch a list of admins with optional filters for pagination and username."""
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app import billing, feature_flags
    from app.db.models import User
    from app.models.user import UserStatus
    from config import ONLINE_WINDOW_MINUTES

    rows = crud.get_admins(db, offset, limit, username)
    user_counts = dict(
        db.query(User.admin_id, func.count(User.id))
        .filter(User.admin_id.isnot(None))
        .group_by(User.admin_id)
        .all()
    )
    cutoff = datetime.utcnow() - timedelta(minutes=ONLINE_WINDOW_MINUTES)
    online_counts = dict(
        db.query(User.admin_id, func.count(User.id))
        .filter(
            User.admin_id.isnot(None),
            User.online_at.isnot(None),
            User.online_at >= cutoff,
            User.status.in_((UserStatus.active, UserStatus.on_hold)),
        )
        .group_by(User.admin_id)
        .all()
    )
    parent_ids = {
        int(row.parent_admin_id)
        for row in rows
        if getattr(row, "parent_admin_id", None)
    }
    parent_names: dict = {}
    if parent_ids:
        from app.db.models import Admin as AdminRow

        parent_names = {
            int(r.id): r.username
            for r in db.query(AdminRow)
            .filter(AdminRow.id.in_(list(parent_ids)))
            .all()
        }

    out: List[Admin] = []
    for row in rows:
        item = Admin.model_validate(row)
        item.users_count = int(user_counts.get(row.id, 0) or 0)
        item.online_users = int(online_counts.get(row.id, 0) or 0)
        pid = getattr(row, "parent_admin_id", None)
        if pid:
            item.parent_admin_username = parent_names.get(int(pid))
        if feature_flags.is_enabled("billing") and not row.is_sudo:
            try:
                item.wallet_balance = billing.get_or_create_wallet(db, row.id).balance
            except Exception:
                item.wallet_balance = 0
            item.prepaid_traffic_remaining = int(
                getattr(row, "prepaid_traffic_remaining", 0) or 0
            )
        out.append(item)
    return out


@router.post("/admin/{username}/users/disable", responses={403: responses._403, 404: responses._404})
def disable_all_active_users(
    dbadmin: Admin = Depends(get_admin_by_username),
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Disable all active users under a specific admin"""
    crud.disable_all_active_users(db=db, admin=dbadmin)
    startup_config = xray.config.include_db_users()
    xray.core.restart(startup_config)
    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)
    return {"detail": "Users successfully disabled"}


@router.post("/admin/{username}/users/activate", responses={403: responses._403, 404: responses._404})
def activate_all_disabled_users(
    dbadmin: Admin = Depends(get_admin_by_username),
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Activate all disabled users under a specific admin"""
    crud.activate_all_disabled_users(db=db, admin=dbadmin)
    startup_config = xray.config.include_db_users()
    xray.core.restart(startup_config)
    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)
    return {"detail": "Users successfully activated"}


@router.post(
    "/admin/usage/reset/{username}",
    response_model=Admin,
    responses={403: responses._403},
)
def reset_admin_usage(
    dbadmin: Admin = Depends(get_admin_by_username),
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Resets usage of admin."""
    return crud.reset_admin_usage(db, dbadmin)


@router.get(
    "/admin/usage/{username}",
    response_model=int,
    responses={403: responses._403},
)
def get_admin_usage(
    dbadmin: Admin = Depends(get_admin_by_username),
    current_admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Retrieve the usage of given admin."""
    return dbadmin.users_usage


@router.get("/admin/rbac/matrix", responses={403: responses._403})
def rbac_matrix(_: Admin = Depends(Admin.check_sudo_admin)):
    from app.rbac import PERMISSIONS, get_role_matrix

    return {"permissions": sorted(PERMISSIONS), "roles": get_role_matrix()}


@router.put("/admin/rbac/roles/{role}", responses={403: responses._403})
def update_rbac_role(
    role: str,
    payload: dict = Body(...),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    from app.rbac import save_role_permissions

    perms = payload.get("permissions")
    if not isinstance(perms, list):
        raise HTTPException(status_code=400, detail="permissions must be a list")
    try:
        save_role_permissions(role, [str(p) for p in perms])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"role": role, "permissions": perms}


@router.get("/admin/sessions", responses={403: responses._403})
def list_admin_sessions(_: Admin = Depends(Admin.check_sudo_admin)):
    from app.utils.admin_sessions import list_sessions

    return {"sessions": list_sessions(limit=200)}


@router.post("/admin/sessions/revoke", responses={403: responses._403})
def revoke_admin_sessions(
    payload: dict = Body(...),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    from app.utils.admin_sessions import revoke_user_sessions

    username = str(payload.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    revoke_user_sessions(username)
    return {"detail": f"Sessions revoked for {username}"}


@router.get("/admin/sso/public")
def sso_public():
    """Public OIDC discovery for the login page (no auth)."""
    from app.utils.oidc import authorize_url, oidc_enabled

    if not oidc_enabled():
        return {"enabled": False}
    return {"enabled": True, "authorize_url": authorize_url()}


@router.post("/admin/sso/callback", response_model=Token)
def sso_callback(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Exchange an OIDC authorization code for a panel admin token."""
    from app.utils.oidc import OidcError, exchange_code, fetch_userinfo, oidc_enabled, username_from_claims

    if not oidc_enabled():
        raise HTTPException(status_code=404, detail="OIDC is not configured")

    code = payload.get("code")
    if not code or not isinstance(code, str):
        raise HTTPException(status_code=400, detail="code is required")

    client_ip = get_client_ip(request)
    enforce_admin_ip_allowlist(client_ip)

    redirect_uri = payload.get("redirect_uri")
    try:
        tokens = exchange_code(code, redirect_uri if isinstance(redirect_uri, str) else None)
        userinfo = fetch_userinfo(tokens["access_token"])
        username = username_from_claims(userinfo)
    except OidcError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    dbadmin = crud.get_admin(db, username)
    if dbadmin is None:
        raise HTTPException(status_code=403, detail="No matching admin account for SSO identity")

    if client_ip not in LOGIN_NOTIFY_WHITE_LIST:
        report.login(username, "🔐 SSO", client_ip, True)

    from app.utils.admin_sessions import record_login

    record_login(username, ip=client_ip, is_sudo=dbadmin.is_sudo)

    return Token(**admin_token_bundle(username, dbadmin.is_sudo))


@router.get("/admin/sso")
def sso_config(_: Admin = Depends(Admin.check_sudo_admin)):
    from app.utils.oidc import authorize_url, oidc_enabled

    enabled = oidc_enabled()
    authorize = authorize_url() if enabled else ""
    return {
        "enabled": enabled,
        "issuer": OIDC_ISSUER or None,
        "client_id": OIDC_CLIENT_ID or None,
        "redirect_uri": OIDC_REDIRECT_URI or None,
        "authorize_url": authorize or None,
    }
