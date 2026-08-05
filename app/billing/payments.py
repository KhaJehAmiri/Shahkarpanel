"""Payment intent orchestration: top-up and portal buy/renew."""
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import billing, xray
from app.billing.providers import available_providers, get_provider, provider_supports_intent
from app.db.models import Admin, PaymentIntent, Plan, User
from app.models.user import UserStatus
from app.portal import (
    apply_plan_to_user,
    assert_can_add_account,
    create_account_from_plan,
    create_user_order,
    get_owned_account,
    mark_order_applied,
)
from app.tenant.plan_ops import assert_plan_for_user
from app import platform_settings as ps
from config import PORTAL_DIRECT_PAYMENT, PORTAL_PAYMENT_PENDING_TTL_MINUTES


def portal_payment_ttl_minutes() -> int:
    return max(5, int(PORTAL_PAYMENT_PENDING_TTL_MINUTES or 120))


def portal_payment_expires_at(created_at: Optional[datetime] = None) -> datetime:
    base = created_at or datetime.utcnow()
    from datetime import timedelta

    return base + timedelta(minutes=portal_payment_ttl_minutes())


def is_portal_payment_expired(intent: PaymentIntent, *, now: Optional[datetime] = None) -> bool:
    """True when a still-pending portal intent is past its TTL."""
    if intent is None or intent.kind not in ("portal_renew", "portal_purchase"):
        return False
    if (intent.status or "").strip().lower() != "pending":
        return False
    now = now or datetime.utcnow()
    extra = intent.extra or {}
    raw = extra.get("expires_at")
    if raw:
        try:
            exp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                from datetime import timezone

                exp = exp.astimezone(timezone.utc).replace(tzinfo=None)
            return now >= exp
        except Exception:
            pass
    created = intent.created_at or now
    return now >= portal_payment_expires_at(created)


def expire_stale_portal_payments(db: Session, *, limit: int = 200) -> int:
    """Mark overdue pending portal payments as expired. Returns count updated."""
    from app import portal_tx

    now = datetime.utcnow()
    q = (
        db.query(PaymentIntent)
        .filter(
            PaymentIntent.kind.in_(("portal_renew", "portal_purchase")),
            PaymentIntent.status == "pending",
        )
        .order_by(PaymentIntent.id.asc())
        .limit(max(1, min(int(limit), 1000)))
    )
    n = 0
    for intent in q.all():
        if not is_portal_payment_expired(intent, now=now):
            continue
        intent.status = "expired"
        intent.completed_at = now
        extra = dict(intent.extra or {})
        extra["expired_at"] = now.isoformat() + "Z"
        if not extra.get("expires_at"):
            extra["expires_at"] = portal_payment_expires_at(intent.created_at).isoformat() + "Z"
        intent.extra = extra
        try:
            plan_name = extra.get("plan_name")
            portal_tx.attach_tx_message(intent, plan_name=plan_name, event="expired")
        except Exception:
            pass
        db.add(intent)
        n += 1
    if n:
        db.commit()
    return n


def resume_portal_payment_payload(db: Session, intent: PaymentIntent) -> dict:
    """Rebuild checkout payload for a still-pending portal payment."""
    if intent.kind not in ("portal_renew", "portal_purchase"):
        raise HTTPException(status_code=400, detail="Not a portal payment")
    if is_portal_payment_expired(intent):
        expire_stale_portal_payments(db)
        db.refresh(intent)
    if (intent.status or "").strip().lower() != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Payment is {intent.status}; only pending payments can be resumed",
        )

    extra = dict(intent.extra or {})
    provider = (intent.provider or "").strip().lower()
    if provider == "card":
        from app.billing.providers import list_cards_for_admin, public_card_payload
        from app.db import crud

        dbadmin = crud.get_admin_by_id(db, intent.admin_id) if intent.admin_id else None
        cards = list_cards_for_admin(dbadmin)
        return {
            "provider": "card",
            "payment_id": intent.id,
            "amount": intent.amount,
            "status": intent.status,
            "card_id": extra.get("card_id") or "",
            "card_number": extra.get("card_number") or "",
            "card_holder": extra.get("card_holder") or "",
            "card_bank": extra.get("card_bank") or "",
            "cards": [public_card_payload(c) for c in cards],
            "instructions": "Transfer to the card and submit the purchase for review.",
            "action": str(extra.get("action") or "renew"),
            "username": extra.get("new_username") or extra.get("target_username"),
            "plan_name": extra.get("plan_name"),
            "expires_at": extra.get("expires_at"),
            "checkout_url": None,
            "confirm_token": None,
        }

    # Gateway / demo — reuse stored checkout fields when present
    return {
        "provider": provider,
        "payment_id": intent.id,
        "amount": intent.amount,
        "status": intent.status,
        "checkout_url": extra.get("checkout_url"),
        "confirm_token": extra.get("confirm_token"),
        "instructions": extra.get("instructions") or "Complete payment via the gateway.",
        "action": str(extra.get("action") or "renew"),
        "username": extra.get("new_username") or extra.get("target_username"),
        "plan_name": extra.get("plan_name"),
        "expires_at": extra.get("expires_at"),
        "card_id": None,
        "card_number": None,
        "card_holder": None,
        "card_bank": None,
        "cards": [],
    }

def _validate_amount(amount: int, *, min_amount: Optional[int] = None) -> int:
    value = int(amount)
    min_amt = int(min_amount) if min_amount is not None else ps.get_int("payment.min_amount", 100)
    max_amt = ps.get_int("payment.max_amount", 100_000_000)
    if value < min_amt:
        raise HTTPException(
            status_code=422,
            detail=f"Minimum payment amount is {min_amt}",
        )
    if value > max_amt:
        raise HTTPException(
            status_code=422,
            detail=f"Maximum payment amount is {max_amt}",
        )
    return value


# Reseller self-service wallet top-up floor (toman / minor units as configured).
RESELLER_TOPUP_MIN_AMOUNT = 1_000_000


def _require_provider(name: str, dbadmin=None, *, kind: Optional[str] = None) -> None:
    name = (name or "").strip().lower()
    if name == "demo" and not ps.get_bool("payment.demo_enabled", False):
        raise HTTPException(
            status_code=403,
            detail="Demo gateway is disabled — use card, CentralPay, or Stripe",
        )
    if not provider_supports_intent(name):
        raise HTTPException(status_code=422, detail=f"Provider '{name}' is not available")
    if name == "centralpay":
        from app.billing.providers import admin_may_use_centralpay

        # Wallet top-up uses the platform merchant account — any reseller may pay.
        # Portal checkout still requires per-reseller CentralPay opt-in.
        if kind != "topup":
            if dbadmin is not None and not admin_may_use_centralpay(dbadmin):
                raise HTTPException(
                    status_code=403,
                    detail="CentralPay is not enabled for this reseller",
                )
    if name == "card":
        from app.billing.providers import resolve_card_for_admin, resolve_platform_card

        # Wallet top-ups pay the platform card; portal purchases use the owner card.
        if kind == "topup":
            if resolve_platform_card() is None:
                raise HTTPException(
                    status_code=403,
                    detail="Platform card payment is not configured",
                )
        elif dbadmin is not None and resolve_card_for_admin(dbadmin) is None:
            raise HTTPException(
                status_code=403,
                detail="Card payment is not configured for this reseller",
            )


def _billing_admin_id(db: Session, dbuser: User) -> int:
    admin_id = dbuser.admin_id
    if admin_id:
        return admin_id
    sudo = db.query(Admin).filter(Admin.is_sudo.is_(True)).order_by(Admin.id).first()
    if sudo is None:
        raise HTTPException(status_code=400, detail="No panel admin available for payment")
    return sudo.id


def public_base_from_request(request) -> str:
    """Public origin for payment return URLs (honours reverse-proxy headers)."""
    xf_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    xf_host = (
        (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        or (request.headers.get("host") or "").strip()
    )
    if xf_host:
        scheme = xf_proto or (request.url.scheme if getattr(request, "url", None) else None) or "https"
        return f"{scheme}://{xf_host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def create_topup_payment(
    db: Session,
    admin_id: int,
    amount: int,
    provider: str,
    *,
    public_base: Optional[str] = None,
    card_id: Optional[str] = None,
) -> tuple[PaymentIntent, dict]:
    from app.db import crud

    dbadmin = crud.get_admin_by_id(db, admin_id)
    _require_provider(provider, dbadmin, kind="topup")
    value = _validate_amount(amount, min_amount=RESELLER_TOPUP_MIN_AMOUNT)
    extra: dict = {}
    if public_base:
        extra["public_base"] = public_base.rstrip("/")
    if card_id:
        extra["card_id"] = str(card_id).strip()
    intent = PaymentIntent(
        kind="topup",
        admin_id=admin_id,
        amount=value,
        provider=provider,
        status="pending",
        extra=extra or None,
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    try:
        instructions = get_provider(provider).create_payment(intent)
        db.commit()
        db.refresh(intent)
        return intent, instructions
    except ValueError as exc:
        intent.status = "failed"
        extra_fail = dict(intent.extra or {})
        extra_fail["create_error"] = str(exc)[:500]
        intent.extra = extra_fail
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        intent.status = "failed"
        extra_fail = dict(intent.extra or {})
        extra_fail["create_error"] = str(exc)[:500]
        intent.extra = extra_fail
        db.commit()
        raise HTTPException(status_code=502, detail=f"Payment provider error: {exc}") from exc


def create_portal_payment(
    db: Session,
    dbuser: User,
    plan_id: int,
    provider: str,
    *,
    action: str = "renew",
    target_username: Optional[str] = None,
    new_username: Optional[str] = None,
    public_base: Optional[str] = None,
    card_id: Optional[str] = None,
) -> tuple[PaymentIntent, dict]:
    """Start portal checkout.

    action=renew  → renew an owned account (default: login account)
    action=purchase → buy a brand-new VPN account (new_username required)
    """
    if not PORTAL_DIRECT_PAYMENT:
        raise HTTPException(status_code=404, detail="Direct portal payment is disabled")

    from app.db import crud

    billing_admin_id = _billing_admin_id(db, dbuser)
    dbadmin = crud.get_admin_by_id(db, billing_admin_id)
    _require_provider(provider, dbadmin, kind="portal")

    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan or not plan.enabled:
        raise HTTPException(status_code=404, detail="Plan not found")
    assert_plan_for_user(db, dbuser.admin_id, plan)

    # Fail before the customer pays if the reseller cannot cover the master
    # unlimited tariff — avoids capturing money then 402'ing on apply.
    from app.billing.unlimited_create import (
        UnlimitedCreateChargeError,
        prepare_unlimited_create_charge,
    )

    billing_admin = crud.get_admin_by_id(db, dbuser.admin_id) if dbuser.admin_id else None
    try:
        prepare_unlimited_create_charge(
            db,
            billing_admin,
            data_limit=plan.data_limit,
            count=1,
            commercial_plan=plan,
        )
    except UnlimitedCreateChargeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    price = int(plan.price or 0)
    if price <= 0:
        raise HTTPException(status_code=422, detail="Use free renew/create for free plans")

    action = (action or "renew").strip().lower()
    extra: dict = {
        "action": action,
        "plan_id": plan.id,
        "portal_user_id": int(dbuser.id),
        "plan_name": plan.name,
    }
    if public_base:
        extra["public_base"] = public_base.rstrip("/")
    if card_id:
        extra["card_id"] = str(card_id).strip()
    # Auto-expire unpaid checkouts so users don't leave dangling "awaiting payment" rows.
    extra["expires_at"] = portal_payment_expires_at().isoformat() + "Z"

    if action == "purchase":
        username = (new_username or "").strip().lower()
        if len(username) < 3:
            raise HTTPException(status_code=400, detail="New username required (3–32 chars)")
        if crud.get_user(db, username):
            raise HTTPException(status_code=409, detail="Username already exists")
        # Refuse before the customer pays; the cap must never eat a paid intent.
        assert_can_add_account(db, dbuser)
        extra["new_username"] = username
        kind = "portal_purchase"
        # Payer is the portal login; target user created on completion.
        target_user_id = dbuser.id
    else:
        target = get_owned_account(db, dbuser, target_username or dbuser.username)
        kind = "portal_renew"
        target_user_id = target.id
        extra["target_username"] = target.username

    intent = PaymentIntent(
        kind=kind,
        admin_id=billing_admin_id,
        user_id=target_user_id,
        plan_id=plan.id,
        amount=price,
        provider=provider,
        status="pending",
        extra=extra,
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    try:
        instructions = get_provider(provider).create_payment(intent)
        db.commit()
        db.refresh(intent)
        return intent, instructions
    except ValueError as exc:
        intent.status = "failed"
        extra_fail = dict(intent.extra or {})
        extra_fail["create_error"] = str(exc)[:500]
        intent.extra = extra_fail
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        intent.status = "failed"
        extra_fail = dict(intent.extra or {})
        extra_fail["create_error"] = str(exc)[:500]
        intent.extra = extra_fail
        db.commit()
        raise HTTPException(status_code=502, detail=f"Payment provider error: {exc}") from exc


def set_payment_card(
    db: Session,
    intent: PaymentIntent,
    card_id: str,
) -> PaymentIntent:
    """Switch the frozen card on a pending card payment (before receipt submit)."""
    from app.billing.providers import (
        apply_card_to_intent_extra,
        list_cards_for_admin,
        list_platform_cards,
        pick_payment_card,
    )
    from app.db import crud

    if intent.provider != "card":
        raise HTTPException(status_code=400, detail="Not a card payment")
    if intent.status != "pending":
        raise HTTPException(status_code=409, detail="Card can only be changed before receipt submit")
    cid = (card_id or "").strip()
    if not cid:
        raise HTTPException(status_code=422, detail="card_id required")

    if intent.kind == "topup":
        cards = list_platform_cards()
    else:
        dbadmin = crud.get_admin_by_id(db, intent.admin_id) if intent.admin_id else None
        cards = list_cards_for_admin(dbadmin)
    card = pick_payment_card(cards, cid)
    if not card or card.get("id") != cid:
        raise HTTPException(status_code=404, detail="Card not found")
    intent.extra = apply_card_to_intent_extra(intent.extra, card)
    db.commit()
    db.refresh(intent)
    return intent


def submit_card_payment(
    db: Session,
    intent: PaymentIntent,
    *,
    note: Optional[str] = None,
    receipt_meta: Optional[dict] = None,
) -> PaymentIntent:
    if intent.provider != "card":
        raise HTTPException(status_code=400, detail="Not a card payment")
    if intent.status not in ("pending", "awaiting_review"):
        raise HTTPException(status_code=409, detail="Payment is not pending")
    extra = dict(intent.extra or {})
    if note:
        extra["user_note"] = str(note)[:500]
    if receipt_meta:
        extra.update(receipt_meta)
    extra["submitted_at"] = datetime.utcnow().isoformat() + "Z"
    intent.extra = extra
    intent.status = "awaiting_review"
    try:
        from app.portal_tx import attach_tx_message

        attach_tx_message(
            intent,
            plan_name=(extra.get("plan_name") or None),
            event="submitted",
        )
    except Exception:
        pass
    db.commit()
    db.refresh(intent)
    try:
        from app.web_push import notify_card_payment_submitted

        notify_card_payment_submitted(db, intent)
    except Exception:
        pass
    try:
        from app.portal_push import notify_portal_payment

        notify_portal_payment(db, intent, event="submitted")
    except Exception:
        pass
    return intent


_CARD_REVIEW_KINDS = ("portal_renew", "portal_purchase", "topup")


def _owner_admin(db: Session, intent: PaymentIntent) -> Optional[Admin]:
    from app.db.models import Admin as AdminRow

    if intent.admin_id is None:
        return None
    return db.query(AdminRow).filter(AdminRow.id == int(intent.admin_id)).first()


def _assert_can_review_card(db: Session, admin: Admin, intent: PaymentIntent) -> None:
    """Portal card → owning reseller only; master only for master-owned users.

    Wallet top-up → sudo only.
    """
    if intent.kind == "topup":
        if not getattr(admin, "is_sudo", False):
            raise HTTPException(status_code=403, detail="Only the platform owner can approve wallet top-ups")
        return
    if intent.kind not in ("portal_renew", "portal_purchase"):
        return
    owner = _owner_admin(db, intent)
    reviewer_id = getattr(admin, "id", None)
    if owner is not None and reviewer_id is not None and int(owner.id) == int(reviewer_id):
        return
    if getattr(admin, "is_sudo", False) and owner is not None and bool(getattr(owner, "is_sudo", False)):
        return
    raise HTTPException(
        status_code=403,
        detail="Reseller portal card orders are reviewed by that reseller, not the platform owner",
    )


def approve_portal_payment(db: Session, intent: PaymentIntent, *, reviewer: Optional[Admin] = None) -> PaymentIntent:
    """Approve a card payment (portal purchase/renew or reseller wallet top-up)."""
    if intent.kind not in _CARD_REVIEW_KINDS:
        raise HTTPException(status_code=400, detail="Not a reviewable card payment")
    if intent.status not in ("pending", "awaiting_review"):
        raise HTTPException(status_code=409, detail="Payment is not awaiting review")
    if intent.provider != "card":
        raise HTTPException(status_code=400, detail="Only card payments can be manually approved")
    if reviewer is not None:
        _assert_can_review_card(db, reviewer, intent)
    return complete_payment(db, intent, {"admin_approved": True})


def reject_portal_payment(
    db: Session,
    intent: PaymentIntent,
    *,
    reason: Optional[str] = None,
    reviewer: Optional[Admin] = None,
) -> PaymentIntent:
    """Reject a card payment (portal purchase/renew or reseller wallet top-up)."""
    if intent.kind not in _CARD_REVIEW_KINDS:
        raise HTTPException(status_code=400, detail="Not a reviewable card payment")
    if intent.status not in ("pending", "awaiting_review"):
        raise HTTPException(status_code=409, detail="Payment is not awaiting review")
    if reviewer is not None:
        _assert_can_review_card(db, reviewer, intent)
    extra = dict(intent.extra or {})
    if reason:
        extra["reject_reason"] = str(reason)[:500]
    extra["rejected_at"] = datetime.utcnow().isoformat() + "Z"
    intent.extra = extra
    intent.status = "rejected"
    try:
        from app.portal_tx import attach_tx_message

        attach_tx_message(
            intent,
            plan_name=(extra.get("plan_name") or None),
            event="rejected",
        )
    except Exception:
        pass
    db.commit()
    db.refresh(intent)
    return intent


def list_portal_payments_for_admin(
    db: Session,
    admin: Admin,
    *,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[PaymentIntent]:
    """Card/portal queue for this admin.

    Resellers see only their own portal card purchases/renewals.
    Sudo sees master-owned portal orders + reseller wallet top-ups — never
    reseller customer card orders (those are reviewed by that reseller).
    """
    from sqlalchemy import and_, or_

    from app.db.models import Admin as AdminRow

    if getattr(admin, "is_sudo", False):
        sudo_ids = [int(r[0]) for r in db.query(AdminRow.id).filter(AdminRow.is_sudo.is_(True)).all()]
        q = db.query(PaymentIntent).filter(
            or_(
                and_(
                    PaymentIntent.kind.in_(("portal_renew", "portal_purchase")),
                    PaymentIntent.admin_id.in_(sudo_ids or [-1]),
                ),
                and_(
                    PaymentIntent.kind == "topup",
                    PaymentIntent.provider == "card",
                ),
            )
        )
    else:
        admin_pk = getattr(admin, "id", None)
        if admin_pk is None:
            return []
        q = db.query(PaymentIntent).filter(
            PaymentIntent.kind.in_(("portal_renew", "portal_purchase")),
            PaymentIntent.admin_id == admin_pk,
        )
    if status:
        q = q.filter(PaymentIntent.status == status)
    return q.order_by(PaymentIntent.id.desc()).limit(max(1, min(limit, 200))).all()


def _apply_topup(db: Session, intent: PaymentIntent) -> None:
    billing.add_transaction(
        db,
        intent.admin_id,
        intent.amount,
        type="topup",
        description=f"Wallet top-up via {intent.provider}",
        reference=f"payment:{intent.id}",
    )
    try:
        from app.billing.usage_billing import bill_reseller_usage
        from app.db import crud
        from app.quota import enforce_reseller_traffic_caps, restore_users_everywhere

        admin = crud.get_admin_by_id(db, intent.admin_id)
        if admin is not None:
            bill_reseller_usage(db, admin)
        _newly, reactivated = enforce_reseller_traffic_caps(db)
        if reactivated:
            db.commit()
            # Restore on a background thread — fleet Finalmask/Xray push must
            # not block the approve HTTP response.
            import threading

            ids = list(reactivated)

            def _restore() -> None:
                try:
                    restore_users_everywhere(ids)
                except Exception:
                    pass

            threading.Thread(target=_restore, name="topup-restore-users", daemon=True).start()
    except Exception:
        pass


def _apply_portal_renew(db: Session, intent: PaymentIntent) -> User:
    dbuser = db.query(User).filter(User.id == intent.user_id).first()
    plan = db.query(Plan).filter(Plan.id == intent.plan_id).first()
    if dbuser is None or plan is None:
        raise HTTPException(status_code=404, detail="Payment target not found")

    order = create_user_order(db, dbuser, plan, status="paid")
    dbuser = apply_plan_to_user(db, dbuser, plan)
    mark_order_applied(db, order)

    from app.billing.unlimited_create import (
        UnlimitedCreateChargeError,
        charge_portal_unlimited_tariff,
    )

    try:
        charge_portal_unlimited_tariff(
            db,
            reseller_admin_id=dbuser.admin_id,
            commercial_plan=plan,
            username=dbuser.username,
            event="portal_renew",
        )
    except UnlimitedCreateChargeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if dbuser.status in (UserStatus.active, UserStatus.on_hold):
        # Fast path only on the HTTP thread. Full ``sync_core_users()`` /
        # ``update_user``→``_push_user_to_nodes`` used to block approve for
        # tens of seconds while every Iran node was dialed.
        try:
            xray.operations.sync_core_users_async()
        except Exception:
            pass
        try:
            from app.xray.serving import sync_main_core_user

            sync_main_core_user(dbuser)
        except Exception:
            pass
        try:
            from app.wireguard.operations import sync_user_change

            sync_user_change()
        except Exception:
            pass
    return dbuser


def _free_username(db: Session, base: str) -> str:
    """First unused variant of ``base`` (``base``, ``base2``, ``base3``, …).

    The name is reserved at checkout time but only created after the money
    lands, so it can be taken meanwhile. A paid purchase must never dead-end on
    a 409 the customer cannot resolve.
    """
    from app.db import crud

    if not crud.get_user(db, base):
        return base
    stem = base[:29]
    for n in range(2, 100):
        candidate = f"{stem}{n}"
        if not crud.get_user(db, candidate):
            return candidate
    return f"{base[:24]}{secrets.token_hex(3)}"


def _apply_portal_purchase(db: Session, intent: PaymentIntent) -> User:
    """Create a new owned VPN account after payment."""
    plan = db.query(Plan).filter(Plan.id == intent.plan_id).first()
    owner = db.query(User).filter(User.id == intent.user_id).first()
    extra = intent.extra or {}
    username = (extra.get("new_username") or "").strip().lower()
    if plan is None or owner is None or not username:
        raise HTTPException(status_code=404, detail="Purchase target not found")

    # Owner row is the portal login that paid.
    dbuser = create_account_from_plan(db, owner, plan, _free_username(db, username))
    order = create_user_order(db, dbuser, plan, status="paid")
    mark_order_applied(db, order)

    from app.billing.unlimited_create import (
        UnlimitedCreateChargeError,
        charge_portal_unlimited_tariff,
    )

    try:
        charge_portal_unlimited_tariff(
            db,
            reseller_admin_id=owner.admin_id,
            commercial_plan=plan,
            username=dbuser.username,
            event="portal_purchase",
        )
    except UnlimitedCreateChargeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # Point intent at the created account for admin UI.
    intent.user_id = dbuser.id
    extra = dict(extra)
    extra["created_username"] = dbuser.username
    if not extra.get("portal_user_id"):
        extra["portal_user_id"] = int(owner.id)
    intent.extra = extra
    db.commit()
    return dbuser


def complete_payment(
    db: Session,
    intent: PaymentIntent,
    payload: dict,
) -> PaymentIntent:
    if intent.status == "completed":
        return intent
    if intent.status not in ("pending", "awaiting_review"):
        raise HTTPException(status_code=409, detail="Payment is not pending")

    provider = get_provider(intent.provider)
    if not provider.verify(intent, payload):
        raise HTTPException(status_code=400, detail="Payment verification failed")

    if intent.kind == "topup":
        _apply_topup(db, intent)
    elif intent.kind == "portal_renew":
        _apply_portal_renew(db, intent)
    elif intent.kind == "portal_purchase":
        _apply_portal_purchase(db, intent)
    else:
        raise HTTPException(status_code=400, detail="Unknown payment kind")

    intent.status = "completed"
    intent.completed_at = datetime.utcnow()
    try:
        from app.portal_tx import attach_tx_message

        extra = intent.extra or {}
        event = "approved" if intent.provider == "card" else "completed"
        attach_tx_message(
            intent,
            plan_name=(extra.get("plan_name") or None),
            event=event,
        )
    except Exception:
        pass
    db.commit()
    db.refresh(intent)
    # Gateway (non-card) wallet top-up: notify the reseller like a native app.
    if intent.kind == "topup" and intent.provider != "card":
        try:
            from app.web_push import notify_topup_result

            notify_topup_result(db, intent, approved=True)
        except Exception:
            pass
    return intent


def get_intent_for_admin(db: Session, payment_id: int, admin_id: int) -> PaymentIntent:
    intent = db.query(PaymentIntent).filter(PaymentIntent.id == payment_id).first()
    if intent is None or intent.admin_id != admin_id:
        raise HTTPException(status_code=404, detail="Payment not found")
    return intent


def get_intent_for_admin_or_sudo(db: Session, payment_id: int, admin: Admin) -> PaymentIntent:
    intent = db.query(PaymentIntent).filter(PaymentIntent.id == payment_id).first()
    if intent is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if getattr(admin, "is_sudo", False):
        # Sudo may open wallet top-ups and master-owned portal orders only.
        if intent.kind == "topup":
            return intent
        if intent.kind in ("portal_renew", "portal_purchase"):
            owner = _owner_admin(db, intent)
            if owner is not None and bool(getattr(owner, "is_sudo", False)):
                return intent
            raise HTTPException(status_code=404, detail="Payment not found")
        return intent
    if intent.admin_id != admin.id:
        raise HTTPException(status_code=404, detail="Payment not found")
    return intent


def get_intent_for_user(db: Session, payment_id: int, user_id: int) -> PaymentIntent:
    intent = db.query(PaymentIntent).filter(PaymentIntent.id == payment_id).first()
    if intent is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    # Allow portal owner to access intents for themselves or their purchases.
    if intent.user_id == user_id:
        return intent
    extra = intent.extra or {}
    # Pending purchase is stored with owner as user_id already.
    owner = db.query(User).filter(User.id == user_id).first()
    if owner and intent.user_id:
        target = db.query(User).filter(User.id == intent.user_id).first()
        if target and (
            target.id == owner.id
            or target.portal_owner_user_id == owner.id
            or (extra.get("action") == "purchase" and intent.user_id == owner.id)
        ):
            return intent
    raise HTTPException(status_code=404, detail="Payment not found")


def list_online_providers() -> list[str]:
    return available_providers(online_only=True)
