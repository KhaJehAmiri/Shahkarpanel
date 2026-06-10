"""Platform settings stored in DB with .env fallbacks (phase 6).

All commercial knobs are editable from the sudo UI under System → Commercial.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.db import GetDB

_lock = threading.Lock()
_cache: Dict[str, Any] = {}

# Registry: key -> (env_fallback_attr_on_config_module, type_name)
SETTING_SPECS: Dict[str, tuple] = {
    "billing.usage_rate_per_gb": ("USAGE_BILLING_RATE_PER_GB", "int"),
    "billing.wallet_low_threshold": ("WALLET_LOW_BALANCE_THRESHOLD", "int"),
    "billing.job_interval_seconds": ("JOB_BILL_USAGE_INTERVAL", "int"),
    # Display label for prices in the portal/panel (e.g. "تومان", "USD").
    "billing.currency_label": ("", "str"),
    "payment.demo_enabled": ("PAYMENT_DEMO_ENABLED", "bool"),
    "payment.min_amount": ("PAYMENT_MIN_AMOUNT", "int"),
    "payment.max_amount": ("PAYMENT_MAX_AMOUNT", "int"),
    "payment.stripe_enabled": ("", "bool"),
    "payment.stripe_publishable_key": ("", "str"),
    "payment.stripe_secret_key": ("", "secret"),
    "payment.stripe_webhook_secret": ("", "secret"),
    "reseller.sub_reseller_max": ("SUB_RESELLER_MAX_PER_PARENT", "int"),
    "reseller.default_commission_percent": ("", "int"),
}

SECRET_KEYS = frozenset({
    "payment.stripe_secret_key",
    "payment.stripe_webhook_secret",
})


def _env_default(key: str) -> Any:
    spec = SETTING_SPECS.get(key)
    if not spec or not spec[0]:
        if key == "payment.stripe_enabled":
            return False
        if key == "reseller.default_commission_percent":
            return 0
        return None
    import config as cfg

    return getattr(cfg, spec[0], None)


def _coerce(value: Any, type_name: str) -> Any:
    if value is None:
        return None
    if type_name == "int":
        return int(value)
    if type_name == "bool":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "on")
    return str(value)


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()


def get_setting(key: str, default: Any = None) -> Any:
    with _lock:
        if key in _cache:
            return _cache[key]

    from app.db.models import PlatformSetting
    from sqlalchemy.exc import OperationalError

    resolved: Any = None
    with GetDB() as db:
        try:
            row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
            if row is not None and row.value is not None:
                resolved = row.value
        except OperationalError:
            resolved = None

    if resolved is None:
        env_val = _env_default(key)
        resolved = env_val if env_val is not None else default

    spec = SETTING_SPECS.get(key)
    if spec:
        resolved = _coerce(resolved, spec[1])

    with _lock:
        _cache[key] = resolved
    return resolved


def get_int(key: str, default: int = 0) -> int:
    v = get_setting(key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    v = get_setting(key, default)
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes", "on")


def get_str(key: str, default: str = "") -> str:
    v = get_setting(key, default)
    return str(v) if v is not None else default


def set_setting(key: str, value: Any) -> None:
    if key not in SETTING_SPECS:
        raise ValueError(f"Unknown setting: {key}")
    from app.db.models import PlatformSetting

    spec = SETTING_SPECS[key]
    stored = _coerce(value, spec[1])
    with GetDB() as db:
        row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
        if row is None:
            row = PlatformSetting(key=key, value=stored, updated_at=datetime.utcnow())
            db.add(row)
        else:
            row.value = stored
            row.updated_at = datetime.utcnow()
        db.commit()
    invalidate_cache()


def mask_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    s = str(value)
    if len(s) <= 8:
        return "••••••••"
    return f"{s[:4]}…{s[-4:]}"


def list_settings_for_ui() -> List[Dict[str, Any]]:
    rows = []
    for key, (_, type_name) in SETTING_SPECS.items():
        raw = get_setting(key)
        display = raw
        if key in SECRET_KEYS and raw:
            display = mask_secret(str(raw))
        rows.append({
            "key": key,
            "value": display,
            "type": type_name,
            "has_secret": key in SECRET_KEYS,
            "is_set": raw is not None and raw != "" and raw is not False,
        })
    return rows


def update_settings_bulk(updates: Dict[str, Any]) -> None:
    for key, value in updates.items():
        if key not in SETTING_SPECS:
            continue
        if key in SECRET_KEYS:
            if not value or str(value).startswith("••") or "…" in str(value):
                continue
        set_setting(key, value)
    refresh_payment_providers()


def refresh_payment_providers() -> None:
    from app.billing import providers as prov

    prov.reload_providers()
