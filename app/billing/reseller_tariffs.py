"""Reseller wholesale plan tariffs — owned by platform, managed under Resellers.

Completely separate from master retail ``Plan`` rows. Sudo defines any mix of
volume + unlimited tariffs here; when a reseller creates an account or their
customer buys/renews a matching commercial plan, ``price`` is debited from the
reseller wallet (type=plan_sale).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.db.models import Admin, Plan, ResellerPlanTariff, ResellerPlanTariffOverride


class ResellerTariffError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def normalize_data_limit(data_limit) -> Optional[int]:
    """None = unlimited; otherwise positive bytes."""
    if data_limit is None:
        return None
    try:
        n = int(data_limit)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n


def is_unlimited_data_limit(data_limit) -> bool:
    return normalize_data_limit(data_limit) is None


def list_tariffs(db: Session, *, enabled_only: bool = False) -> List[ResellerPlanTariff]:
    q = db.query(ResellerPlanTariff).order_by(
        ResellerPlanTariff.duration_days.asc().nullslast(),
        ResellerPlanTariff.data_limit.asc().nullslast(),
        ResellerPlanTariff.id.asc(),
    )
    if enabled_only:
        q = q.filter(ResellerPlanTariff.enabled.is_(True))
    return q.all()


def get_tariff(db: Session, tariff_id: int) -> Optional[ResellerPlanTariff]:
    return db.query(ResellerPlanTariff).filter(ResellerPlanTariff.id == tariff_id).first()


def _normalize_positive_int(value, *, allow_zero: bool = False) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    if n == 0 and not allow_zero:
        return None
    return n


def create_tariff(
    db: Session,
    *,
    name: str,
    price: int,
    data_limit: Optional[int] = None,
    duration_days: Optional[int] = None,
    device_limit: Optional[int] = None,
    speed_limit_up: Optional[int] = None,
    speed_limit_down: Optional[int] = None,
    enabled: bool = True,
) -> ResellerPlanTariff:
    name = (name or "").strip()
    if not name:
        raise ResellerTariffError("Name is required")
    row = ResellerPlanTariff(
        name=name[:128],
        price=max(0, int(price or 0)),
        data_limit=normalize_data_limit(data_limit),
        duration_days=int(duration_days) if duration_days not in (None, "") else None,
        device_limit=_normalize_positive_int(device_limit),
        speed_limit_up=_normalize_positive_int(speed_limit_up),
        speed_limit_down=_normalize_positive_int(speed_limit_down),
        enabled=bool(enabled),
        created_at=datetime.utcnow(),
    )
    if row.duration_days is not None and row.duration_days <= 0:
        row.duration_days = None
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_tariff(
    db: Session,
    row: ResellerPlanTariff,
    *,
    name: Optional[str] = None,
    price: Optional[int] = None,
    data_limit: Any = ...,
    duration_days: Any = ...,
    device_limit: Any = ...,
    speed_limit_up: Any = ...,
    speed_limit_down: Any = ...,
    enabled: Optional[bool] = None,
) -> ResellerPlanTariff:
    if name is not None:
        name = name.strip()
        if not name:
            raise ResellerTariffError("Name is required")
        row.name = name[:128]
    if price is not None:
        row.price = max(0, int(price))
    if data_limit is not ...:
        row.data_limit = normalize_data_limit(data_limit)
    if duration_days is not ...:
        if duration_days in (None, ""):
            row.duration_days = None
        else:
            d = int(duration_days)
            row.duration_days = d if d > 0 else None
    if device_limit is not ...:
        row.device_limit = _normalize_positive_int(device_limit)
    if speed_limit_up is not ...:
        row.speed_limit_up = _normalize_positive_int(speed_limit_up)
    if speed_limit_down is not ...:
        row.speed_limit_down = _normalize_positive_int(speed_limit_down)
    if enabled is not None:
        row.enabled = bool(enabled)
    db.commit()
    db.refresh(row)
    return row


def delete_tariff(db: Session, row: ResellerPlanTariff) -> None:
    (
        db.query(ResellerPlanTariffOverride)
        .filter(ResellerPlanTariffOverride.tariff_id == row.id)
        .delete(synchronize_session=False)
    )
    db.delete(row)
    db.commit()


def get_tariff_override(
    db: Session,
    *,
    admin_id: int,
    tariff_id: int,
) -> Optional[ResellerPlanTariffOverride]:
    return (
        db.query(ResellerPlanTariffOverride)
        .filter(
            ResellerPlanTariffOverride.admin_id == admin_id,
            ResellerPlanTariffOverride.tariff_id == tariff_id,
        )
        .first()
    )


def effective_tariff_price(
    db: Session,
    admin: Optional[Admin],
    tariff: ResellerPlanTariff,
) -> int:
    """Catalog price, or per-reseller override when set."""
    catalog = int(tariff.price or 0)
    if admin is None:
        return catalog
    ov = get_tariff_override(db, admin_id=admin.id, tariff_id=tariff.id)
    if ov is not None and ov.price is not None:
        return int(ov.price)
    return catalog


def effective_tariff_offer(
    db: Session,
    admin: Admin,
    tariff: ResellerPlanTariff,
) -> Dict[str, Any]:
    catalog_price = int(tariff.price or 0)
    price = catalog_price
    price_overridden = False
    ov = get_tariff_override(db, admin_id=admin.id, tariff_id=tariff.id)
    if ov is not None and ov.price is not None:
        price = int(ov.price)
        price_overridden = True
    return {
        "id": tariff.id,
        "name": tariff.name,
        "enabled": bool(tariff.enabled),
        "data_limit": tariff.data_limit,
        "duration_days": tariff.duration_days,
        "is_unlimited": is_unlimited_data_limit(tariff.data_limit),
        "catalog_price": catalog_price,
        "price": price,
        "price_overridden": price_overridden,
        "overridden": price_overridden,
        "created_at": tariff.created_at,
    }


def list_tariffs_for_admin(
    db: Session,
    admin: Admin,
    *,
    enabled_only: bool = False,
) -> List[Dict[str, Any]]:
    return [
        effective_tariff_offer(db, admin, row)
        for row in list_tariffs(db, enabled_only=enabled_only)
    ]


def upsert_tariff_override(
    db: Session,
    *,
    admin_id: int,
    tariff_id: int,
    price: Optional[int],
    commit: bool = False,
) -> Optional[ResellerPlanTariffOverride]:
    """Set or clear price override. ``price is None`` removes the row."""
    if price is not None and int(price) < 0:
        raise ResellerTariffError("Override price cannot be negative")

    ov = get_tariff_override(db, admin_id=admin_id, tariff_id=tariff_id)
    if price is None:
        if ov is not None:
            db.delete(ov)
            if commit:
                db.commit()
        return None

    if ov is None:
        ov = ResellerPlanTariffOverride(
            admin_id=admin_id,
            tariff_id=tariff_id,
            price=int(price),
        )
        db.add(ov)
    else:
        ov.price = int(price)
    if commit:
        db.commit()
        db.refresh(ov)
    return ov


def tariff_to_dict(row: ResellerPlanTariff) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "price": int(row.price or 0),
        "data_limit": row.data_limit,
        "duration_days": row.duration_days,
        "device_limit": row.device_limit,
        "speed_limit_up": int(row.speed_limit_up) if row.speed_limit_up is not None else None,
        "speed_limit_down": int(row.speed_limit_down) if row.speed_limit_down is not None else None,
        "enabled": bool(row.enabled),
        "created_at": row.created_at,
        "is_unlimited": is_unlimited_data_limit(row.data_limit),
    }


def locked_limit_overrides(tariff: Optional[ResellerPlanTariff]) -> Dict[str, Any]:
    """Fields master locked on this tariff — applied to reseller create/edit."""
    if tariff is None:
        return {}
    out: Dict[str, Any] = {}
    if tariff.device_limit is not None and int(tariff.device_limit) > 0:
        out["device_limit"] = int(tariff.device_limit)
    if tariff.speed_limit_up is not None and int(tariff.speed_limit_up) > 0:
        out["speed_limit_up"] = int(tariff.speed_limit_up)
    if tariff.speed_limit_down is not None and int(tariff.speed_limit_down) > 0:
        out["speed_limit_down"] = int(tariff.speed_limit_down)
    return out


def locked_limit_overrides_from_plan(plan: Optional[Plan]) -> Dict[str, Any]:
    """Device lock copied from a retail Plan row (Plans have no speed fields)."""
    if plan is None:
        return {}
    dl = getattr(plan, "device_limit", None)
    if dl is not None and int(dl) > 0:
        return {"device_limit": int(dl)}
    return {}


def _normalize_duration_days(duration_days) -> Optional[int]:
    if duration_days in (None, ""):
        return None
    try:
        d = int(duration_days)
    except (TypeError, ValueError):
        return None
    return d if d > 0 else None


def _merge_limit_locks(*parts: Dict[str, Any]) -> Dict[str, Any]:
    """Merge lock dicts; device/speed use the strictest (minimum) positive value."""
    out: Dict[str, Any] = {}
    for part in parts:
        if not part:
            continue
        for key, value in part.items():
            if value is None:
                continue
            try:
                n = int(value)
            except (TypeError, ValueError):
                continue
            if n <= 0:
                continue
            if key not in out or n < int(out[key]):
                out[key] = n
    return out


def match_plans_for_limits(
    db: Session,
    *,
    data_limit=None,
    duration_days: Optional[int] = None,
) -> List[Plan]:
    """Enabled retail plans with the same volume + duration shape (exact)."""
    want_dl = normalize_data_limit(data_limit)
    want_dur = _normalize_duration_days(duration_days)
    rows = (
        db.query(Plan)
        .filter(Plan.enabled.is_(True))
        .order_by(Plan.id.asc())
        .all()
    )
    matched: List[Plan] = []
    for plan in rows:
        if normalize_data_limit(plan.data_limit) != want_dl:
            continue
        if _normalize_duration_days(plan.duration_days) != want_dur:
            continue
        matched.append(plan)
    return matched


def resolve_plan_limit_locks(
    db: Session,
    *,
    data_limit=None,
    duration_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Strictest device_limit among matching retail plans."""
    locks: Dict[str, Any] = {}
    for plan in match_plans_for_limits(
        db, data_limit=data_limit, duration_days=duration_days
    ):
        locks = _merge_limit_locks(locks, locked_limit_overrides_from_plan(plan))
    return locks


def default_unlimited_tariff_locks(db: Session) -> Dict[str, Any]:
    """Floor locks from any unlimited wholesale tariff (when no exact match).

    Masters often set ``device_limit`` on 30/60/90 unlimited tariffs while
    resellers still sell open-ended or oddly-shaped retail plans. Without this
    floor those plans bypass the device cap entirely.
    """
    locks: Dict[str, Any] = {}
    for tariff in list_tariffs(db, enabled_only=True):
        if not is_unlimited_data_limit(tariff.data_limit):
            continue
        locks = _merge_limit_locks(locks, locked_limit_overrides(tariff))
    return locks


def duration_days_from_expire(expire) -> Optional[int]:
    """Best-effort days remaining from a unix expire timestamp."""
    if expire in (None, 0, "0"):
        return None
    try:
        ts = int(expire)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    secs = ts - int(datetime.utcnow().timestamp())
    if secs <= 0:
        return None
    days = int(round(secs / 86400.0))
    return days if days > 0 else None


def duration_days_from_on_hold(on_hold_expire_duration) -> Optional[int]:
    """Package length in days from on_hold duration (seconds)."""
    if on_hold_expire_duration in (None, 0, "0"):
        return None
    try:
        secs = int(on_hold_expire_duration)
    except (TypeError, ValueError):
        return None
    if secs <= 0:
        return None
    days = int(round(secs / 86400.0))
    return days if days > 0 else None


def duration_days_for_create_payload(user) -> Optional[int]:
    """Duration shape for create: prefer on_hold package length, else expire."""
    hold = duration_days_from_on_hold(getattr(user, "on_hold_expire_duration", None))
    if hold is not None:
        return hold
    return duration_days_from_expire(getattr(user, "expire", None))


# Date-pickers often set expire to calendar midnight / end-of-day, so
# ``round((expire-now)/86400)`` lands on 29 or 31 when the reseller picked
# "30 days". Snap within this window to a catalog duration — never across
# packages (30 must not become 60).
_DURATION_SNAP_TOLERANCE_DAYS = 1


def snap_duration_to_catalog(
    want_days: Optional[int],
    catalog_days: Sequence[int],
    *,
    tolerance: int = _DURATION_SNAP_TOLERANCE_DAYS,
) -> Optional[int]:
    """Return ``want_days`` or the nearest catalog day within ``tolerance``."""
    if want_days is None:
        return None
    want = int(want_days)
    if want <= 0:
        return None
    catalog = sorted({int(d) for d in catalog_days if d is not None and int(d) > 0})
    if not catalog:
        return want
    if want in catalog:
        return want
    near = [d for d in catalog if abs(d - want) <= int(tolerance)]
    if not near:
        return want
    return min(near, key=lambda d: (abs(d - want), d))


def resolve_locked_limits_for_admin(
    db: Session,
    admin: Optional[Admin],
    *,
    data_limit=None,
    duration_days: Optional[int] = None,
    expire=None,
    commercial_plan: Optional[Plan] = None,
) -> Dict[str, Any]:
    """For non-sudo resellers, return device/speed locks from tariff and plans."""
    if admin is None or getattr(admin, "is_sudo", False):
        return {}

    if commercial_plan is not None:
        data_limit = getattr(commercial_plan, "data_limit", data_limit)
        dur = _normalize_duration_days(getattr(commercial_plan, "duration_days", None))
    else:
        dur = _normalize_duration_days(duration_days)
        if dur is None:
            dur = duration_days_from_expire(expire)

    tariff = match_tariff(db, data_limit=data_limit, duration_days=dur)
    locks = _merge_limit_locks(
        resolve_plan_limit_locks(db, data_limit=data_limit, duration_days=dur),
        locked_limit_overrides_from_plan(commercial_plan),
        locked_limit_overrides(tariff),
    )
    # No exact tariff/plan device cap: still enforce master's unlimited floor.
    if "device_limit" not in locks and is_unlimited_data_limit(data_limit):
        locks = _merge_limit_locks(locks, default_unlimited_tariff_locks(db))
    return locks


def apply_locked_limits_to_user_payload(payload, overrides: Dict[str, Any]):
    """Force locked fields onto a Pydantic user create/modify model."""
    if not overrides:
        return payload
    return payload.model_copy(update=overrides)


def enforce_reseller_create_locks(db: Session, admin: Optional[Admin], new_user):
    """Force master-locked device/speed onto a UserCreate for resellers."""
    duration_days = duration_days_for_create_payload(new_user)
    locks = resolve_locked_limits_for_admin(
        db,
        admin,
        data_limit=getattr(new_user, "data_limit", None),
        duration_days=duration_days,
        expire=getattr(new_user, "expire", None),
    )
    return apply_locked_limits_to_user_payload(new_user, locks), duration_days


def match_tariff(
    db: Session,
    *,
    data_limit=None,
    duration_days: Optional[int] = None,
) -> Optional[ResellerPlanTariff]:
    """Find best enabled wholesale tariff for the given limits."""
    want_dl = normalize_data_limit(data_limit)
    want_dur = int(duration_days) if duration_days not in (None, "") else None
    if want_dur is not None and want_dur <= 0:
        want_dur = None

    rows = list_tariffs(db, enabled_only=True)
    same_volume = [t for t in rows if normalize_data_limit(t.data_limit) == want_dl]
    if not same_volume:
        return None

    if want_dur is not None:
        catalog_durs = [
            int(t.duration_days)
            for t in same_volume
            if t.duration_days is not None and int(t.duration_days) > 0
        ]
        snapped = snap_duration_to_catalog(want_dur, catalog_durs)
        exact = [
            t
            for t in same_volume
            if t.duration_days is not None and int(t.duration_days) == snapped
        ]
        if exact:
            return sorted(exact, key=lambda t: (int(t.price or 0), t.id))[0]
        # Farther than snap tolerance — do not silently pick another package.
        return None

    # Open-ended request: only open-ended tariffs (never a timed 30/60/90).
    open_ended = [t for t in same_volume if t.duration_days is None]
    if not open_ended:
        return None
    return sorted(open_ended, key=lambda t: (int(t.price or 0), t.id))[0]


def match_tariff_for_plan(db: Session, plan: Plan) -> Optional[ResellerPlanTariff]:
    return match_tariff(
        db,
        data_limit=getattr(plan, "data_limit", None),
        duration_days=getattr(plan, "duration_days", None),
    )


def prepare_reseller_tariff_charge(
    db: Session,
    admin: Optional[Admin],
    *,
    data_limit=None,
    duration_days: Optional[int] = None,
    commercial_plan: Optional[Plan] = None,
    count: int = 1,
    require_match: bool = True,
) -> Tuple[Optional[ResellerPlanTariff], int]:
    """Validate wallet for ``count`` matching wholesale tariffs.

    Returns ``(tariff, unit_price)``. No matching tariff / sudo / billing off →
    ``(None, 0)`` unless ``require_match`` and a relevant tariff catalog exists
    (then ``ResellerTariffError`` 400). Insufficient balance → 402.
    """
    if admin is None or getattr(admin, "is_sudo", False):
        return None, 0
    if count < 1:
        return None, 0

    from app import feature_flags

    if not feature_flags.is_enabled("billing"):
        return None, 0

    if commercial_plan is not None:
        data_limit = getattr(commercial_plan, "data_limit", data_limit)
        duration_days = getattr(commercial_plan, "duration_days", duration_days)
        tariff = match_tariff_for_plan(db, commercial_plan)
    else:
        tariff = match_tariff(db, data_limit=data_limit, duration_days=duration_days)

    if tariff is None:
        if require_match:
            assert_reseller_shape_allowed(
                db, admin, data_limit=data_limit, duration_days=duration_days
            )
        return None, 0

    price = effective_tariff_price(db, admin, tariff)
    if price <= 0:
        return tariff, 0

    from app.billing import get_or_create_wallet

    total = price * int(count)
    wallet = get_or_create_wallet(db, admin.id)
    if int(wallet.balance or 0) < total:
        raise ResellerTariffError(
            f"Insufficient wallet balance — need {total} for {count}× «{tariff.name}», "
            f"have {wallet.balance}",
            status_code=402,
        )
    return tariff, price


def _norm_expire(expire) -> Optional[int]:
    if expire in (None, 0, "0"):
        return None
    try:
        ts = int(expire)
    except (TypeError, ValueError):
        return None
    return ts if ts > 0 else None


def assert_reseller_shape_allowed(
    db: Session,
    admin: Optional[Admin],
    *,
    data_limit=None,
    duration_days: Optional[int] = None,
) -> None:
    """Reject shapes that bypass the wholesale catalog when tariffs exist."""
    if admin is None or getattr(admin, "is_sudo", False):
        return
    from app import feature_flags

    if not feature_flags.is_enabled("billing"):
        return

    tariffs = list_tariffs(db, enabled_only=True)
    if not tariffs:
        return

    if match_tariff(db, data_limit=data_limit, duration_days=duration_days) is not None:
        return

    if is_unlimited_data_limit(data_limit):
        ul = [t for t in tariffs if is_unlimited_data_limit(t.data_limit)]
        if not ul:
            return
        examples = sorted(
            {
                int(t.duration_days)
                for t in ul
                if t.duration_days is not None and int(t.duration_days) > 0
            }
        )
        hint = (
            f" (e.g. {', '.join(str(d) + ' days' for d in examples)})"
            if examples
            else ""
        )
        got = (
            f" (received {int(duration_days)} days)"
            if duration_days not in (None, "")
            else " (no expiry)"
        )
        raise ResellerTariffError(
            "Unlimited accounts must use a duration that matches a wholesale tariff"
            + hint
            + got
            + ". Creating without expiry (or a non-matching duration) is not allowed.",
            status_code=400,
        )

    vol = [t for t in tariffs if not is_unlimited_data_limit(t.data_limit)]
    if vol:
        raise ResellerTariffError(
            "No wholesale tariff matches this data limit / duration. "
            "Pick a volume and period that exists under Resellers → Tariffs.",
            status_code=400,
        )


def billable_duration_candidates(
    old_expire, new_expire
) -> List[int]:
    """Possible package lengths for a modify that touches expiry."""
    now = int(datetime.utcnow().timestamp())
    old_e = _norm_expire(old_expire)
    new_e = _norm_expire(new_expire)
    if new_e is None:
        return []
    out: List[int] = []
    from_now = int(round((new_e - now) / 86400.0))
    if from_now > 0:
        out.append(from_now)
    if old_e is not None and old_e > now and new_e > old_e + 3600:
        added = int(round((new_e - old_e) / 86400.0))
        if added > 0 and added not in out:
            out.append(added)
    return out


def match_tariff_for_modify(
    db: Session,
    *,
    data_limit=None,
    old_expire=None,
    new_expire=None,
) -> Optional[ResellerPlanTariff]:
    for dur in billable_duration_candidates(old_expire, new_expire):
        hit = match_tariff(db, data_limit=data_limit, duration_days=dur)
        if hit is not None:
            return hit
    # Data-limit-only change (no expiry extension): match remaining duration shape.
    old_e = _norm_expire(old_expire)
    new_e = _norm_expire(new_expire)
    if old_e == new_e or (
        old_e is not None
        and new_e is not None
        and abs(int(new_e) - int(old_e)) <= 3600
    ):
        dur = duration_days_from_expire(new_expire)
        return match_tariff(db, data_limit=data_limit, duration_days=dur)
    return None


def assert_reseller_modify_shape_allowed(
    db: Session,
    admin: Optional[Admin],
    *,
    old_data_limit=None,
    old_expire=None,
    next_data_limit=None,
    next_expire=None,
) -> None:
    """Block clearing expiry / open-ended unlimited when timed tariffs exist."""
    if admin is None or getattr(admin, "is_sudo", False):
        return
    from app import feature_flags

    if not feature_flags.is_enabled("billing"):
        return

    tariffs = list_tariffs(db, enabled_only=True)
    if not tariffs:
        return

    old_e = _norm_expire(old_expire)
    new_e = _norm_expire(next_expire)
    # Removing expiry on an unlimited account while timed unlimited tariffs exist.
    if (
        old_e is not None
        and new_e is None
        and is_unlimited_data_limit(next_data_limit)
    ):
        timed_ul = [
            t
            for t in tariffs
            if is_unlimited_data_limit(t.data_limit)
            and t.duration_days is not None
            and int(t.duration_days) > 0
        ]
        if timed_ul:
            raise ResellerTariffError(
                "Cannot remove expiry on unlimited accounts while wholesale "
                "duration tariffs are configured — renew with a matching period instead.",
                status_code=400,
            )

    # Extending / setting expiry without a matching tariff.
    candidates = billable_duration_candidates(old_expire, next_expire)
    if not candidates and normalize_data_limit(old_data_limit) == normalize_data_limit(
        next_data_limit
    ):
        return

    if match_tariff_for_modify(
        db,
        data_limit=next_data_limit,
        old_expire=old_expire,
        new_expire=next_expire,
    ) is not None:
        return

    if candidates and is_unlimited_data_limit(next_data_limit):
        ul = [t for t in tariffs if is_unlimited_data_limit(t.data_limit)]
        if ul:
            raise ResellerTariffError(
                "Expiry must match a wholesale tariff duration "
                "(extension/set does not match 30/60/90…).",
                status_code=400,
            )

    if normalize_data_limit(old_data_limit) != normalize_data_limit(next_data_limit):
        assert_reseller_shape_allowed(
            db,
            admin,
            data_limit=next_data_limit,
            duration_days=duration_days_from_expire(next_expire),
        )


def should_charge_reseller_modify(
    dbuser,
    tariff: ResellerPlanTariff,
    *,
    next_expire=None,
    old_expire=None,
    old_data_limit=None,
    next_data_limit=None,
) -> bool:
    """Whether this modify should debit wallet (anti double-charge)."""
    if tariff is None:
        return False
    paid_id = getattr(dbuser, "reseller_tariff_charged_id", None)
    paid_expire = _norm_expire(getattr(dbuser, "reseller_tariff_charged_expire", None))
    new_e = _norm_expire(next_expire)
    old_e = _norm_expire(old_expire)

    extended = bool(
        new_e is not None
        and (
            old_e is None
            or old_e <= int(datetime.utcnow().timestamp())
            or new_e > old_e + 3600
        )
    )
    data_changed = normalize_data_limit(old_data_limit) != normalize_data_limit(
        next_data_limit
    )

    if paid_id is None:
        return extended or data_changed

    if extended:
        if paid_expire is None:
            return True
        if new_e is not None and new_e > int(paid_expire) + 3600:
            return True
        # Extended but still within already-paid window (clock skew / no-op).
        return False

    if data_changed and int(paid_id) != int(tariff.id):
        return True
    return False


def mark_user_tariff_charged(dbuser, tariff: Optional[ResellerPlanTariff]) -> None:
    if tariff is None or dbuser is None:
        return
    dbuser.reseller_tariff_charged_id = int(tariff.id)
    dbuser.reseller_tariff_charged_expire = _norm_expire(getattr(dbuser, "expire", None))


def mark_users_tariff_charged(
    db: Session,
    usernames: Sequence[str],
    tariff: Optional[ResellerPlanTariff],
) -> None:
    if tariff is None or not usernames:
        return
    from app.db.models import User

    rows = db.query(User).filter(User.username.in_(list(usernames))).all()
    for row in rows:
        mark_user_tariff_charged(row, tariff)
    db.commit()


def prepare_reseller_modify_charge(
    db: Session,
    admin: Optional[Admin],
    dbuser,
    *,
    next_data_limit=None,
    next_expire=None,
) -> Tuple[Optional[ResellerPlanTariff], int]:
    """Wallet check for a reseller edit that upgrades/renews into a tariff."""
    if admin is None or getattr(admin, "is_sudo", False):
        return None, 0
    from app import feature_flags

    if not feature_flags.is_enabled("billing"):
        return None, 0

    old_data = getattr(dbuser, "data_limit", None)
    old_expire = getattr(dbuser, "expire", None)

    assert_reseller_modify_shape_allowed(
        db,
        admin,
        old_data_limit=old_data,
        old_expire=old_expire,
        next_data_limit=next_data_limit,
        next_expire=next_expire,
    )

    tariff = match_tariff_for_modify(
        db,
        data_limit=next_data_limit,
        old_expire=old_expire,
        new_expire=next_expire,
    )
    if tariff is None:
        return None, 0

    if not should_charge_reseller_modify(
        dbuser,
        tariff,
        next_expire=next_expire,
        old_expire=old_expire,
        old_data_limit=old_data,
        next_data_limit=next_data_limit,
    ):
        return None, 0

    price = effective_tariff_price(db, admin, tariff)
    if price <= 0:
        return tariff, 0

    from app.billing import get_or_create_wallet

    wallet = get_or_create_wallet(db, admin.id)
    if int(wallet.balance or 0) < price:
        raise ResellerTariffError(
            f"Insufficient wallet balance — need {price} for «{tariff.name}», "
            f"have {wallet.balance}",
            status_code=402,
        )
    return tariff, price


def charge_reseller_tariff(
    db: Session,
    admin: Admin,
    *,
    tariff: ResellerPlanTariff,
    unit_price: int,
    usernames: Sequence[str],
    event: str = "create",
):
    if not usernames or unit_price <= 0:
        return None
    if admin is None or getattr(admin, "is_sudo", False):
        return None

    from app.billing import add_transaction

    n = len(usernames)
    total = unit_price * n
    sample = usernames[0] if n == 1 else f"{usernames[0]} +{n - 1} more"
    label = {
        "create": "Reseller tariff create",
        "modify": "Reseller tariff modify/renew",
        "portal_purchase": "Reseller tariff portal purchase",
        "portal_renew": "Reseller tariff portal renew",
    }.get(event, f"Reseller tariff {event}")
    return add_transaction(
        db,
        admin.id,
        -total,
        type="plan_sale",
        description=f"{label} ×{n} — {tariff.name} ({sample})",
        reference=f"reseller_tariff_{event}:tariff:{tariff.id}:n:{n}:user:{usernames[0]}",
    )


def charge_portal_plan_tariff(
    db: Session,
    *,
    reseller_admin_id: Optional[int],
    commercial_plan: Plan,
    username: str,
    event: str,
):
    """Debit matching wholesale tariff after portal buy/renew (reseller only)."""
    if not reseller_admin_id:
        return None
    from app.db import crud

    admin = crud.get_admin_by_id(db, int(reseller_admin_id))
    if admin is None or getattr(admin, "is_sudo", False):
        return None

    tariff, unit = prepare_reseller_tariff_charge(
        db, admin, commercial_plan=commercial_plan, count=1, require_match=True
    )
    if tariff is None:
        return None
    tx = None
    if unit > 0:
        tx = charge_reseller_tariff(
            db, admin, tariff=tariff, unit_price=unit, usernames=[username], event=event
        )
    dbuser = crud.get_user(db, username)
    if dbuser is not None:
        mark_user_tariff_charged(dbuser, tariff)
        db.commit()
    return tx
