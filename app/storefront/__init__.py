"""Public storefront: resolve reseller context, customer signup, reseller apply."""
from __future__ import annotations

import secrets
import string
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import platform_settings as ps
from app.db import crud
from app.db.models import Admin, BrandingSettings, Plan, ResellerApplication, Tenant
from app.models.admin import AdminCreate
from app.models.user import USERNAME_REGEXP, UserCreate, UserStatusCreate
from app.tenant import branding_scope_admin_id, plan_ops, resolve_branding
from app.tenant.sub_reseller import create_sub_reseller
from app.utils.jwt import create_portal_token


def _platform_storefront_on() -> bool:
    return bool(ps.get_bool("storefront.enabled", True))


def ensure_invite_code(db: Session, admin: Admin) -> str:
    if admin.invite_code:
        return admin.invite_code
    alphabet = string.ascii_lowercase + string.digits
    for _ in range(12):
        code = "".join(secrets.choice(alphabet) for _ in range(10))
        if db.query(Admin).filter(Admin.invite_code == code).first() is None:
            admin.invite_code = code
            db.commit()
            db.refresh(admin)
            return code
    raise HTTPException(status_code=500, detail="Could not allocate invite code")


def rotate_invite_code(db: Session, admin: Admin) -> str:
    admin.invite_code = None
    db.commit()
    return ensure_invite_code(db, admin)


def resolve_context(
    db: Session,
    request: Request,
    *,
    tenant: Optional[str] = None,
    domain: Optional[str] = None,
    ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve storefront owner admin + branding from Host / slug / invite ref."""
    host = (domain or (request.headers.get("host") or "").split(":")[0] or "").strip().lower()
    slug = (tenant or "").strip().lower() or None
    invite = (ref or "").strip().lower() or None

    owner: Optional[Admin] = None
    tenant_row: Optional[Tenant] = None
    via = "platform"

    if invite:
        owner = db.query(Admin).filter(Admin.invite_code == invite).first()
        if owner is None:
            raise HTTPException(status_code=404, detail="Invite code not found")
        via = "invite"
        # Sudo invite recruits top-level resellers (no parent); leave owner=None for apply,
        # but keep invite on context for auto-approve.
        if owner.is_sudo:
            ctx_sudo_invite = owner
            owner = None
        else:
            ctx_sudo_invite = None
            if owner.tenant_id:
                tenant_row = db.query(Tenant).filter(Tenant.id == owner.tenant_id).first()
    else:
        ctx_sudo_invite = None

    # Invite already pinned the context — don't override with slug/host.
    branding_admin_id: Optional[int] = None
    if via != "invite":
        if owner is None and slug:
            tenant_row = db.query(Tenant).filter(Tenant.slug == slug).first()
            if tenant_row is None:
                raise HTTPException(status_code=404, detail="Store not found")
            if tenant_row.owner_admin_id:
                owner = crud.get_admin_by_id(db, tenant_row.owner_admin_id)
            via = "slug"

        if owner is None and host:
            row = (
                db.query(BrandingSettings)
                .filter(BrandingSettings.domain == host)
                .first()
            )
            if row and row.tenant_id is not None:
                tenant_row = db.query(Tenant).filter(Tenant.id == row.tenant_id).first()
                # Sub-reseller domain → that admin; tenant default → owner.
                if getattr(row, "admin_id", None):
                    owner = crud.get_admin_by_id(db, int(row.admin_id))
                    branding_admin_id = int(row.admin_id)
                elif tenant_row and tenant_row.owner_admin_id:
                    owner = crud.get_admin_by_id(db, tenant_row.owner_admin_id)
                via = "domain"

    tenant_id = tenant_row.id if tenant_row else (owner.tenant_id if owner else None)
    if branding_admin_id is None and owner is not None:
        branding_admin_id = branding_scope_admin_id(db, owner)
    branding = resolve_branding(db, tenant_id, admin_id=branding_admin_id)

    platform_on = _platform_storefront_on()
    platform_signup = bool(ps.get_bool("storefront.public_signup_enabled", True))
    platform_apply = bool(ps.get_bool("storefront.reseller_apply_enabled", True))

    if owner is not None:
        signup_enabled = (
            platform_on
            and platform_signup
            and bool(getattr(owner, "public_signup_enabled", True))
        )
        apply_enabled = (
            platform_on
            and platform_apply
            and bool(getattr(owner, "reseller_apply_enabled", True))
        )
        headline = (owner.storefront_headline or "").strip() or None
        tagline = (owner.storefront_tagline or "").strip() or None
        tenant_slug = tenant_row.slug if tenant_row else None
        invite_code = owner.invite_code
    else:
        signup_enabled = platform_on and platform_signup
        apply_enabled = platform_on and platform_apply
        headline = None
        tagline = None
        tenant_slug = None
        invite_code = None

    # Keep headline empty when unset — frontend supplies localized marketing copy.
    # Never echo panel_title as headline (duplicates the brand mark).
    if headline and headline.lower() == (branding.get("panel_title") or "").strip().lower():
        headline = None
    if not headline:
        headline = ""
    if not tagline:
        tagline = ""

    return {
        "owner": owner,
        "tenant": tenant_row,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "via": via,
        "branding": branding,
        "signup_enabled": signup_enabled,
        "reseller_apply_enabled": apply_enabled,
        "headline": headline,
        "tagline": tagline,
        "invite_code": invite_code,
        "ref": invite,
        "storefront_enabled": platform_on,
        "sudo_invite": bool(ctx_sudo_invite),
    }


def public_plans_for_owner(db: Session, owner: Optional[Admin]) -> List[Plan]:
    if owner is not None:
        return plan_ops.get_plans_for_user_reseller(db, owner.id, enabled_only=True)
    return plan_ops.get_global_plans(db, enabled_only=True)


def plan_to_public(plan: Plan) -> Dict[str, Any]:
    return {
        "id": plan.id,
        "name": plan.name,
        "price": int(plan.price or 0),
        "data_limit": plan.data_limit,
        "duration_days": plan.duration_days,
        "device_limit": plan.device_limit,
    }


def storefront_payload(db: Session, ctx: Dict[str, Any]) -> Dict[str, Any]:
    branding = ctx["branding"]
    plans = [plan_to_public(p) for p in public_plans_for_owner(db, ctx["owner"])]
    currency = ps.get_str("billing.currency_label", "") or ""
    return {
        "storefront_enabled": ctx["storefront_enabled"],
        "signup_enabled": ctx["signup_enabled"],
        "reseller_apply_enabled": ctx["reseller_apply_enabled"],
        "tenant_slug": ctx["tenant_slug"],
        "ref": ctx["ref"],
        "headline": ctx["headline"],
        "tagline": ctx["tagline"],
        "currency_label": currency,
        "branding": {
            "panel_title": branding.get("panel_title"),
            "logo_url": branding.get("logo_url"),
            "favicon_url": branding.get("favicon_url"),
            "primary_color": branding.get("primary_color"),
            "support_url": branding.get("support_url"),
            "domain": branding.get("domain"),
            "panel_url": branding.get("panel_url"),
        },
        "plans": plans,
    }


def _default_proxies() -> Tuple[dict, dict]:
    from app.models.proxy import ProxyTypes

    return {ProxyTypes.VLESS: {}}, {}


def register_customer(
    db: Session,
    ctx: Dict[str, Any],
    *,
    username: str,
    password: str,
    contact: Optional[str] = None,
) -> Dict[str, Any]:
    if not ctx["signup_enabled"]:
        raise HTTPException(status_code=403, detail="Public signup is disabled")

    username = (username or "").strip().lower()
    if not USERNAME_REGEXP.match(username):
        raise HTTPException(
            status_code=400,
            detail="Username only can be 3 to 32 characters and contain a-z, 0-9, and underscores in between.",
        )
    if not password or len(password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    if crud.get_user(db, username):
        raise HTTPException(status_code=409, detail="Username already exists")
    if crud.get_admin(db, username):
        raise HTTPException(status_code=409, detail="Username already exists")

    owner: Optional[Admin] = ctx["owner"]
    proxies, inbounds = _default_proxies()
    note_bits = ["public-signup"]
    if contact:
        note_bits.append(f"contact:{contact.strip()[:200]}")
    try:
        user = UserCreate(
            username=username,
            proxies=proxies,
            inbounds=inbounds,
            status=UserStatusCreate.active,
            expire=0,
            data_limit=0,
            portal_enabled=True,
            portal_password=password,
            note=" | ".join(note_bits),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        dbuser = crud.create_user(db, user, admin=owner)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    dbuser.must_change_credentials = False
    db.commit()

    # Bind subscription panel when possible (same as portal purchase).
    try:
        from app.subscription.panel_balance import bind_user_to_panel, default_panel_for_create

        panel_ep = default_panel_for_create(db, owner)
        if panel_ep is not None:
            bind_user_to_panel(
                db,
                user_id=dbuser.id,
                username=dbuser.username,
                endpoint=panel_ep,
                source="public-signup",
            )
    except Exception:
        pass

    # Optional free plan (price == 0) auto-apply for better first experience.
    try:
        free_plans = [
            p for p in public_plans_for_owner(db, owner) if int(p.price or 0) == 0
        ]
        if free_plans:
            from app.portal import apply_plan_to_user

            apply_plan_to_user(db, dbuser, free_plans[0])
    except Exception:
        pass

    return {
        "access_token": create_portal_token(dbuser.username),
        "token_type": "bearer",
        "username": dbuser.username,
        "portal_url": "/portal/",
    }


def apply_reseller(
    db: Session,
    ctx: Dict[str, Any],
    *,
    username: str,
    password: str,
    display_name: Optional[str] = None,
    contact: Optional[str] = None,
    message: Optional[str] = None,
    auto_approve_with_invite: bool = True,
) -> Dict[str, Any]:
    if not ctx["reseller_apply_enabled"]:
        raise HTTPException(status_code=403, detail="Reseller applications are disabled")

    username = (username or "").strip().lower()
    if not USERNAME_REGEXP.match(username):
        raise HTTPException(
            status_code=400,
            detail="Username only can be 3 to 32 characters and contain a-z, 0-9, and underscores in between.",
        )
    if not password or len(password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    if crud.get_admin(db, username) or crud.get_user(db, username):
        raise HTTPException(status_code=409, detail="Username already exists")

    pending = (
        db.query(ResellerApplication)
        .filter(
            ResellerApplication.username == username,
            ResellerApplication.status == "pending",
        )
        .first()
    )
    if pending:
        raise HTTPException(status_code=409, detail="Application already pending")

    parent: Optional[Admin] = ctx["owner"]
    # Invite from a reseller → sub-reseller under that owner.
    if auto_approve_with_invite and parent is not None and ctx.get("ref"):
        try:
            child = create_sub_reseller(
                db,
                parent,
                username=username,
                password=password,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if contact and str(contact).isdigit():
            try:
                child.telegram_id = int(contact)
                db.commit()
            except Exception:
                pass
        return {
            "status": "created",
            "username": child.username,
            "role": "sub_reseller",
            "dashboard_url": "/dashboard/",
            "message": "Sub-reseller account created. You can sign in to the dashboard.",
        }

    # Platform (sudo) invite → top-level reseller immediately.
    if auto_approve_with_invite and parent is None and ctx.get("sudo_invite") and ctx.get("ref"):
        created = crud.create_admin(
            db,
            AdminCreate(
                username=username,
                password=password,
                is_sudo=False,
                role="reseller",
            ),
        )
        if contact and str(contact).isdigit():
            try:
                created.telegram_id = int(contact)
                db.commit()
            except Exception:
                pass
        return {
            "status": "created",
            "username": created.username,
            "role": "reseller",
            "dashboard_url": "/dashboard/",
            "message": "Reseller account created. You can sign in to the dashboard.",
        }

    app = ResellerApplication(
        username=username,
        password_plain=password,
        display_name=(display_name or "").strip() or None,
        contact=(contact or "").strip() or None,
        message=(message or "").strip() or None,
        status="pending",
        parent_admin_id=parent.id if parent else None,
        tenant_id=ctx.get("tenant_id"),
        invite_code=ctx.get("ref"),
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return {
        "status": "pending",
        "id": app.id,
        "username": app.username,
        "message": "Application submitted. An operator will review it shortly.",
    }


def list_applications(
    db: Session,
    actor: Admin,
    *,
    status: Optional[str] = "pending",
) -> List[ResellerApplication]:
    q = db.query(ResellerApplication)
    if status:
        q = q.filter(ResellerApplication.status == status)
    if not actor.is_sudo:
        q = q.filter(ResellerApplication.parent_admin_id == actor.id)
    return q.order_by(ResellerApplication.id.desc()).limit(200).all()


def approve_application(db: Session, actor: Admin, app_id: int) -> Dict[str, Any]:
    app = db.query(ResellerApplication).filter(ResellerApplication.id == app_id).first()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if app.status != "pending":
        raise HTTPException(status_code=400, detail=f"Application is {app.status}")
    if not actor.is_sudo and app.parent_admin_id != actor.id:
        raise HTTPException(status_code=403, detail="Not your application")
    if not app.password_plain:
        raise HTTPException(status_code=400, detail="Application password missing — ask applicant to re-apply")
    if crud.get_admin(db, app.username):
        raise HTTPException(status_code=409, detail="Username already taken")

    if app.parent_admin_id:
        parent = crud.get_admin_by_id(db, app.parent_admin_id)
        if parent is None:
            raise HTTPException(status_code=400, detail="Parent reseller missing")
        child = create_sub_reseller(
            db,
            parent,
            username=app.username,
            password=app.password_plain,
        )
        created = child
        role = "sub_reseller"
    else:
        if not actor.is_sudo:
            raise HTTPException(status_code=403, detail="Only platform owner can approve top-level resellers")
        created = crud.create_admin(
            db,
            AdminCreate(
                username=app.username,
                password=app.password_plain,
                is_sudo=False,
                role="reseller",
            ),
        )
        role = "reseller"

    if app.contact and str(app.contact).isdigit():
        try:
            created.telegram_id = int(app.contact)
        except Exception:
            pass

    app.status = "approved"
    app.password_plain = None
    app.created_admin_id = created.id
    app.reviewed_by_admin_id = actor.id
    app.reviewed_at = datetime.utcnow()
    db.commit()
    return {
        "status": "approved",
        "username": created.username,
        "role": role,
        "dashboard_url": "/dashboard/",
    }


def reject_application(
    db: Session,
    actor: Admin,
    app_id: int,
    *,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    app = db.query(ResellerApplication).filter(ResellerApplication.id == app_id).first()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if app.status != "pending":
        raise HTTPException(status_code=400, detail=f"Application is {app.status}")
    if not actor.is_sudo and app.parent_admin_id != actor.id:
        raise HTTPException(status_code=403, detail="Not your application")
    app.status = "rejected"
    app.password_plain = None
    app.reject_reason = (reason or "").strip()[:256] or None
    app.reviewed_by_admin_id = actor.id
    app.reviewed_at = datetime.utcnow()
    db.commit()
    return {"status": "rejected", "id": app.id}


def mine_storefront(db: Session, admin: Admin) -> Dict[str, Any]:
    row = crud.get_admin(db, admin.username) or (
        crud.get_admin_by_id(db, admin.id) if getattr(admin, "id", None) else None
    )
    if row is None:
        raise HTTPException(status_code=400, detail="Admin not found")
    code = ensure_invite_code(db, row)
    from app import tenant as tenant_svc

    tenant_id = tenant_svc.admin_tenant_id(db, row) if hasattr(tenant_svc, "admin_tenant_id") else row.tenant_id
    scope_admin_id = branding_scope_admin_id(db, row)
    branding = resolve_branding(db, tenant_id, admin_id=scope_admin_id)
    slug = None
    if row.tenant_id:
        t = db.query(Tenant).filter(Tenant.id == row.tenant_id).first()
        slug = t.slug if t else None
    platform_on = _platform_storefront_on()
    # Sub-resellers share the parent tenant slug — pin public links to their
    # invite code (and custom domain when set) so the store is theirs alone.
    is_sub = bool(getattr(row, "parent_admin_id", None))
    custom_domain = (branding.get("domain") or "").strip()
    if is_sub:
        landing = f"https://{custom_domain}/" if custom_domain else f"/register/?ref={code}"
        register = f"https://{custom_domain}/register/?ref={code}" if custom_domain else f"/register/?ref={code}"
    else:
        landing = f"/t/{slug}/" if slug else "/"
        register = f"/register/?tenant={slug}" if slug else "/register/"
    return {
        "invite_code": code,
        "public_signup_enabled": bool(row.public_signup_enabled),
        "reseller_apply_enabled": bool(row.reseller_apply_enabled),
        "storefront_headline": row.storefront_headline,
        "storefront_tagline": row.storefront_tagline,
        "tenant_slug": slug,
        "storefront_enabled": platform_on,
        "effective_signup_enabled": platform_on
        and bool(ps.get_bool("storefront.public_signup_enabled", True))
        and bool(row.public_signup_enabled),
        "effective_reseller_apply_enabled": platform_on
        and bool(ps.get_bool("storefront.reseller_apply_enabled", True))
        and bool(row.reseller_apply_enabled),
        "links": {
            "landing": landing,
            "register": register,
            "become_reseller": f"/become-reseller/?ref={code}",
            "portal": "/portal/",
        },
        "branding": {
            "panel_title": branding.get("panel_title"),
            "logo_url": branding.get("logo_url"),
            "primary_color": branding.get("primary_color"),
            "domain": branding.get("domain"),
            "panel_url": branding.get("panel_url"),
        },
    }


def update_mine_storefront(db: Session, admin: Admin, body: Dict[str, Any]) -> Dict[str, Any]:
    row = crud.get_admin(db, admin.username)
    if row is None:
        raise HTTPException(status_code=400, detail="Admin not found")
    if "public_signup_enabled" in body and body["public_signup_enabled"] is not None:
        row.public_signup_enabled = bool(body["public_signup_enabled"])
    if "reseller_apply_enabled" in body and body["reseller_apply_enabled"] is not None:
        row.reseller_apply_enabled = bool(body["reseller_apply_enabled"])
    if "storefront_headline" in body:
        val = body["storefront_headline"]
        row.storefront_headline = (str(val).strip()[:256] if val else None)
    if "storefront_tagline" in body:
        val = body["storefront_tagline"]
        row.storefront_tagline = (str(val).strip()[:512] if val else None)
    db.commit()
    db.refresh(row)
    return mine_storefront(db, row)
