"""Payment provider abstraction with UI-driven configuration."""
import secrets
from typing import Dict, List

import requests

from app import platform_settings as ps


class PaymentProvider:
    name = "base"

    def create_payment(self, intent) -> dict:
        raise NotImplementedError

    def verify(self, intent, payload: dict) -> bool:
        raise NotImplementedError


class ManualProvider(PaymentProvider):
    name = "manual"

    def create_payment(self, intent) -> dict:
        return {
            "provider": self.name,
            "payment_id": intent.id,
            "amount": intent.amount,
            "instructions": "Pay out-of-band; a sudo admin will confirm the invoice.",
        }

    def verify(self, intent, payload: dict) -> bool:
        return True


class DemoProvider(PaymentProvider):
    name = "demo"

    def create_payment(self, intent) -> dict:
        token = secrets.token_urlsafe(16)
        extra = dict(intent.extra or {})
        extra["confirm_token"] = token
        intent.extra = extra
        return {
            "provider": self.name,
            "payment_id": intent.id,
            "amount": intent.amount,
            "confirm_token": token,
            "instructions": "Demo gateway — submit the confirm token to complete payment.",
        }

    def verify(self, intent, payload: dict) -> bool:
        expected = (intent.extra or {}).get("confirm_token")
        return bool(expected and payload.get("confirm_token") == expected)


class StripeProvider(PaymentProvider):
    name = "stripe"

    def _secret(self) -> str:
        return ps.get_str("payment.stripe_secret_key")

    def create_payment(self, intent) -> dict:
        secret = self._secret()
        if not secret:
            raise ValueError("Stripe secret key not configured")
        extra = dict(intent.extra or {})
        success_url = extra.get("success_url") or "/dashboard/"
        cancel_url = extra.get("cancel_url") or "/dashboard/"
        resp = requests.post(
            "https://api.stripe.com/v1/checkout/sessions",
            auth=(secret, ""),
            data={
                "mode": "payment",
                "success_url": success_url,
                "cancel_url": cancel_url,
                "line_items[0][price_data][currency]": "usd",
                "line_items[0][price_data][unit_amount]": int(intent.amount),
                "line_items[0][price_data][product_data][name]": f"Payment #{intent.id}",
                "line_items[0][quantity]": 1,
                "metadata[payment_intent_id]": str(intent.id),
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            raise ValueError(f"Stripe error: {resp.text[:200]}")
        data = resp.json()
        intent.extra = {**extra, "stripe_session_id": data["id"]}
        return {
            "provider": self.name,
            "payment_id": intent.id,
            "amount": intent.amount,
            "checkout_url": data.get("url"),
            "session_id": data.get("id"),
            "instructions": "Redirect the customer to checkout_url to pay.",
        }

    def verify(self, intent, payload: dict) -> bool:
        if payload.get("stripe_webhook") == "checkout.session.completed":
            sid = (intent.extra or {}).get("stripe_session_id")
            return sid and payload.get("session_id") == sid
        if payload.get("session_id"):
            return self._session_paid(payload["session_id"])
        return False

    def _session_paid(self, session_id: str) -> bool:
        secret = self._secret()
        if not secret:
            return False
        resp = requests.get(
            f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
            auth=(secret, ""),
            timeout=20,
        )
        if resp.status_code >= 400:
            return False
        return resp.json().get("payment_status") == "paid"


_PROVIDERS: Dict[str, PaymentProvider] = {}


def reload_providers() -> None:
    global _PROVIDERS
    _PROVIDERS = {ManualProvider.name: ManualProvider()}
    if ps.get_bool("payment.demo_enabled", True):
        _PROVIDERS[DemoProvider.name] = DemoProvider()
    if ps.get_bool("payment.stripe_enabled") and ps.get_str("payment.stripe_secret_key"):
        _PROVIDERS[StripeProvider.name] = StripeProvider()


reload_providers()


def register_provider(provider: PaymentProvider) -> None:
    _PROVIDERS[provider.name] = provider


def get_provider(name: str = None) -> PaymentProvider:
    return _PROVIDERS.get(name or ManualProvider.name, _PROVIDERS[ManualProvider.name])


def available_providers(*, online_only: bool = False) -> List[str]:
    names = sorted(_PROVIDERS)
    if online_only:
        return [n for n in names if n != ManualProvider.name]
    return names


def provider_supports_intent(name: str) -> bool:
    return name in _PROVIDERS and name != ManualProvider.name
