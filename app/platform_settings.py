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
    # Defaults for the create-package form / optional POST body fields.
    "billing.default_package_price": ("", "int"),
    "billing.default_package_bytes": ("", "int"),
    # Platform plan id(s) whose price is debited from reseller wallets when they
    # create / sell an unlimited-volume account. Multi preferred; single kept
    # for backward compatibility and is merged into the list at read time.
    "billing.reseller_unlimited_plan_id": ("", "int"),
    "billing.reseller_unlimited_plan_ids": ("", "json"),
    "payment.demo_enabled": ("PAYMENT_DEMO_ENABLED", "bool"),
    "payment.min_amount": ("PAYMENT_MIN_AMOUNT", "int"),
    "payment.max_amount": ("PAYMENT_MAX_AMOUNT", "int"),
    # Portal checkout methods (end-user buy/renew).
    "payment.gateway_enabled": ("", "bool"),
    "payment.card_enabled": ("", "bool"),
    "payment.card_number": ("", "str"),
    "payment.card_holder": ("", "str"),
    "payment.card_bank": ("", "str"),
    # Multi-card list: [{id, number, holder, bank, enabled?}]. Scalars remain as legacy mirror.
    "payment.cards": ("", "json"),
    "payment.stripe_enabled": ("", "bool"),
    "payment.stripe_publishable_key": ("", "str"),
    "payment.stripe_secret_key": ("", "secret"),
    "payment.stripe_webhook_secret": ("", "secret"),
    "payment.centralpay_enabled": ("", "bool"),
    "payment.centralpay_api_key": ("", "secret"),
    "payment.centralpay_merchant_id": ("", "str"),
    "payment.centralpay_http_proxy": ("", "secret"),
    # Dedicated CentralPay bridge host (getLink/verify + browser return), not a SOCKS proxy.
    "payment.centralpay_relay_base": ("", "str"),
    "payment.centralpay_relay_secret": ("", "secret"),
    # Browser Web Push (admin/reseller PWA notifications)
    "push.vapid_public_key": ("", "str"),
    "push.vapid_private_key": ("", "secret"),
    "push.vapid_subject": ("", "str"),
    "portal.max_child_accounts": ("PORTAL_MAX_CHILD_ACCOUNTS", "int"),
    "reseller.sub_reseller_max": ("SUB_RESELLER_MAX_PER_PARENT", "int"),
    "reseller.default_commission_percent": ("", "int"),
    # Public white-label storefront (landing + customer signup + reseller apply).
    "storefront.enabled": ("", "bool"),
    "storefront.public_signup_enabled": ("", "bool"),
    "storefront.reseller_apply_enabled": ("", "bool"),
    # Fleet Xray egress guard (BitTorrent / malware / piracy / abuse C2). Default ON.
    "security.egress_guard_enabled": ("", "bool"),
}

SECRET_KEYS = frozenset({
    "payment.stripe_secret_key",
    "payment.stripe_webhook_secret",
    "payment.centralpay_api_key",
    "payment.centralpay_http_proxy",
    "payment.centralpay_relay_secret",
    "push.vapid_private_key",
})


def _env_default(key: str) -> Any:
    spec = SETTING_SPECS.get(key)
    if not spec or not spec[0]:
        if key == "payment.stripe_enabled":
            return False
        if key == "payment.centralpay_enabled":
            return False
        if key in ("payment.gateway_enabled", "payment.card_enabled"):
            return False
        if key in (
            "payment.card_number",
            "payment.card_holder",
            "payment.card_bank",
            "payment.centralpay_merchant_id",
            "push.vapid_public_key",
            "push.vapid_private_key",
        ):
            return ""
        if key == "payment.cards":
            return []
        if key == "push.vapid_subject":
            # Apple rejects mailto:…@*.local — https origin is preferred.
            try:
                from config import PANEL_PUBLIC_ADDRESS

                base = (PANEL_PUBLIC_ADDRESS or "").strip().rstrip("/")
                if base.startswith("https://"):
                    return base
                if base.startswith("http://"):
                    return "https://" + base[len("http://") :]
            except Exception:
                pass
            return "mailto:noreply@example.com"
        if key == "reseller.default_commission_percent":
            return 0
        if key in (
            "storefront.enabled",
            "storefront.public_signup_enabled",
            "storefront.reseller_apply_enabled",
        ):
            return True
        if key == "security.egress_guard_enabled":
            return True
        if key in (
            "billing.default_package_price",
            "billing.default_package_bytes",
            "billing.reseller_unlimited_plan_id",
        ):
            return 0
        if key == "billing.reseller_unlimited_plan_ids":
            return []
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
    if type_name == "json":
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, str):
            import json

            text = value.strip()
            if not text:
                return []
            return json.loads(text)
        return value
    return str(value)


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()


def get_setting(key: str, default: Any = None) -> Any:
    with _lock:
        if key in _cache:
            return _cache[key]

    from sqlalchemy.exc import SQLAlchemyError

    from app.db.models import PlatformSetting

    resolved: Any = None
    with GetDB() as db:
        try:
            row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
            if row is not None and row.value is not None:
                resolved = row.value
        except SQLAlchemyError:
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


def get_json(key: str, default: Any = None) -> Any:
    """Return a JSON setting (list/dict) without stringifying it."""
    spec = SETTING_SPECS.get(key)
    if spec and spec[1] != "json":
        raise ValueError(f"Setting {key} is not json")
    v = get_setting(key, default if default is not None else [])
    if isinstance(v, str):
        import json

        try:
            return json.loads(v) if v.strip() else (default if default is not None else [])
        except json.JSONDecodeError:
            return default if default is not None else []
    return v if v is not None else (default if default is not None else [])


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
        elif type_name == "json":
            import json

            display = json.dumps(raw if raw is not None else [], ensure_ascii=False)
        rows.append({
            "key": key,
            "value": display,
            "type": type_name,
            "has_secret": key in SECRET_KEYS,
            "is_set": raw is not None and raw != "" and raw is not False and raw != [],
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
    # Entering a CentralPay API key activates the gateway; clearing disables it.
    if "payment.centralpay_api_key" in updates:
        raw = updates.get("payment.centralpay_api_key")
        if raw and not str(raw).startswith("••") and "…" not in str(raw):
            set_setting("payment.centralpay_enabled", True)
        elif raw == "" or raw is None:
            # Explicit clear only — masked placeholder keeps current key/flag.
            if not get_str("payment.centralpay_api_key"):
                set_setting("payment.centralpay_enabled", False)
    # Stripe: webhook signing secret is mandatory while enabled.
    if get_bool("payment.stripe_enabled") and not (get_str("payment.stripe_webhook_secret") or "").strip():
        set_setting("payment.stripe_enabled", False)
        refresh_payment_providers()
        raise ValueError(
            "Stripe requires payment.stripe_webhook_secret before it can be enabled "
            "(unsigned webhooks are rejected)."
        )
    refresh_payment_providers()


def refresh_payment_providers() -> None:
    from app.billing import providers as prov

    prov.reload_providers()
