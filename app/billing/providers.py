"""Payment provider abstraction with UI-driven configuration."""
import secrets
from typing import Dict, List, Optional

import requests

from app import platform_settings as ps


class PaymentProvider:
    name = "base"

    def create_payment(self, intent) -> dict:
        raise NotImplementedError

    def verify(self, intent, payload: dict) -> bool:
        raise NotImplementedError


class CardProvider(PaymentProvider):
    """Card-to-card transfer — user pays offline; owning admin/reseller confirms."""

    name = "card"

    def create_payment(self, intent) -> dict:
        from sqlalchemy.orm import object_session

        from app.db.models import Admin

        db = object_session(intent)
        dbadmin = None
        if db is not None and getattr(intent, "admin_id", None):
            dbadmin = db.query(Admin).filter(Admin.id == intent.admin_id).first()
        card = resolve_card_for_admin(dbadmin)
        if not card:
            raise ValueError("Card payment is not configured for this account")
        number = card["number"]
        holder = card.get("holder") or ""
        bank = card.get("bank") or ""
        extra = dict(intent.extra or {})
        extra["card_number"] = number
        extra["card_holder"] = holder
        extra["card_bank"] = bank
        intent.extra = extra
        return {
            "provider": self.name,
            "payment_id": intent.id,
            "amount": intent.amount,
            "card_number": number,
            "card_holder": holder,
            "card_bank": bank,
            "instructions": "Transfer to the card and submit the purchase for review.",
        }

    def verify(self, intent, payload: dict) -> bool:
        # Only admin/reseller approval completes a card payment — never the end-user.
        return bool(payload.get("admin_approved"))


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


class CentralPayProvider(PaymentProvider):
    """Iranian deposit gateway (CentralPay) — amount in TOMAN."""

    name = "centralpay"
    GET_LINK_URL = "https://centralapi.org/webservice/basic/getLink.php"
    VERIFY_URL = "https://centralapi.org/webservice/basic/verify.php"
    # Shared merchant/api_key with the shop bot: bot uses random orderIds in
    # [1_000_000, ~2_001_000_000). Panel uses this offset so CentralPay never
    # sees duplicate_orderId across the two systems.
    ORDER_ID_BASE = 2_100_000_000

    def _api_key(self) -> str:
        return (ps.get_str("payment.centralpay_api_key") or "").strip()

    @classmethod
    def external_order_id(cls, intent_id: int) -> int:
        return int(cls.ORDER_ID_BASE) + int(intent_id)

    @classmethod
    def intent_id_from_order_id(cls, order_id: int) -> int:
        oid = int(order_id)
        base = int(cls.ORDER_ID_BASE)
        if oid >= base:
            return oid - base
        # Legacy panel payments that used bare PaymentIntent.id
        return oid

    def _relay_base(self) -> str:
        return (ps.get_str("payment.centralpay_relay_base") or "").strip().rstrip("/")

    def _relay_secret(self) -> str:
        return (ps.get_str("payment.centralpay_relay_secret") or "").strip()

    def _get_link_url(self) -> str:
        relay = self._relay_base()
        return f"{relay}/getLink" if relay else self.GET_LINK_URL

    def _verify_url(self) -> str:
        relay = self._relay_base()
        return f"{relay}/verify" if relay else self.VERIFY_URL

    def _proxies(self) -> Optional[dict]:
        # Optional legacy HTTP/SOCKS proxy — unused when relay_base is set.
        if self._relay_base():
            return None
        proxy = (ps.get_str("payment.centralpay_http_proxy") or "").strip()
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def _request_headers(self) -> dict:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; Shahkar/1.0; +https://shahkar.local)"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        secret = self._relay_secret()
        if self._relay_base() and secret:
            headers["X-Shahkar-Relay-Secret"] = secret
        return headers

    def _parse_json(self, resp: requests.Response, action: str) -> dict:
        text = resp.text or ""
        if (
            resp.status_code == 403
            or "cloudflare" in text.lower()
            or "<!DOCTYPE html>" in text[:64]
            or "you have been blocked" in text.lower()
        ):
            raise ValueError(
                "CentralPay API is blocked by Cloudflare for this server IP "
                f"({resp.status_code}). Configure payment.centralpay_relay_base "
                "to a reachable bridge host, or payment.centralpay_http_proxy."
            )
        if resp.status_code >= 400:
            raise ValueError(f"CentralPay {action} HTTP {resp.status_code}: {text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ValueError(f"CentralPay {action} bad response: {text[:200]}") from exc

    def _panel_public_base(self) -> str:
        from config import PANEL_PUBLIC_ADDRESS, UVICORN_SSL_CERTFILE

        addr = (PANEL_PUBLIC_ADDRESS or "").strip().rstrip("/")
        if not addr:
            return ""
        if addr.startswith("http://") or addr.startswith("https://"):
            return addr
        return f"https://{addr}"

    def _return_url(self, order_id: int, intent) -> str:
        """Browser return must hit the relay host when configured (egress IP for CP)."""
        relay = self._relay_base()
        if relay:
            return f"{relay}/return?orderId={order_id}"
        extra = intent.extra or {}
        base = (extra.get("public_base") or "").strip().rstrip("/")
        if not base:
            base = self._panel_public_base()
        if not base:
            raise ValueError(
                "CentralPay needs a public panel URL (set PANEL_PUBLIC_ADDRESS or request Host)"
            )
        return f"{base}/api/billing/return/centralpay?orderId={order_id}"

    def create_payment(self, intent) -> dict:
        api_key = self._api_key()
        if not api_key:
            raise ValueError("CentralPay API key not configured")
        amount = int(intent.amount or 0)
        if amount <= 0:
            raise ValueError("Invalid payment amount")
        # CentralPay requires int userId; topup has no user_id — use admin_id.
        user_id = int(intent.user_id or intent.admin_id or 0)
        if user_id <= 0:
            raise ValueError("CentralPay userId missing")
        order_id = self.external_order_id(intent.id)
        return_url = self._return_url(order_id, intent)
        body = {
            "api_key": api_key,
            "type": "deposit",
            "amount": amount,
            "userId": user_id,
            "orderId": order_id,
            "returnUrl": return_url,
        }
        try:
            resp = requests.post(
                self._get_link_url(),
                json=body,
                headers=self._request_headers(),
                proxies=self._proxies(),
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ValueError(f"CentralPay unreachable: {exc}") from exc
        data = self._parse_json(resp, "getLink")
        if not data.get("success"):
            msg = (data.get("data") or {}).get("message") or resp.text[:200]
            raise ValueError(f"CentralPay getLink failed: {msg}")
        redirect = (data.get("data") or {}).get("redirectUrl")
        if not redirect:
            raise ValueError("CentralPay did not return redirectUrl")
        extra = dict(intent.extra or {})
        extra["centralpay_order_id"] = order_id
        extra["centralpay_return_url"] = return_url
        if self._relay_base():
            extra["centralpay_relay_base"] = self._relay_base()
        intent.extra = extra
        return {
            "provider": self.name,
            "payment_id": intent.id,
            "amount": amount,
            "checkout_url": redirect,
            "instructions": "Redirect the customer to CentralPay checkout.",
        }

    def verify(self, intent, payload: dict) -> bool:
        if intent.status == "completed":
            return True
        api_key = self._api_key()
        if not api_key:
            return False
        expected = int(
            (intent.extra or {}).get("centralpay_order_id")
            or self.external_order_id(intent.id)
        )
        order_id = int(payload.get("orderId") or expected)
        if order_id != expected:
            return False
        try:
            resp = requests.post(
                self._verify_url(),
                json={"api_key": api_key, "orderId": order_id},
                headers=self._request_headers(),
                proxies=self._proxies(),
                timeout=30,
            )
            data = self._parse_json(resp, "verify")
        except (requests.RequestException, ValueError):
            return False
        if not data.get("success"):
            return False
        info = data.get("data") or {}
        paid = int(info.get("amount") or 0)
        if paid != int(intent.amount or 0):
            return False
        extra = dict(intent.extra or {})
        if info.get("referenceId") is not None:
            extra["centralpay_reference_id"] = info.get("referenceId")
        if info.get("userCardNumber") is not None:
            extra["centralpay_card"] = str(info.get("userCardNumber"))
        intent.extra = extra
        return True


_PROVIDERS: Dict[str, PaymentProvider] = {}


def reload_providers() -> None:
    global _PROVIDERS
    _PROVIDERS = {ManualProvider.name: ManualProvider()}
    # Card is always registered; availability is resolved per owning admin
    # (platform card for sudo, per-reseller card for resellers).
    _PROVIDERS[CardProvider.name] = CardProvider()
    # Online gateways are only offered when the portal gateway method is enabled.
    if ps.get_bool("payment.gateway_enabled"):
        if ps.get_bool("payment.demo_enabled", True):
            _PROVIDERS[DemoProvider.name] = DemoProvider()
        if ps.get_bool("payment.stripe_enabled") and ps.get_str("payment.stripe_secret_key"):
            _PROVIDERS[StripeProvider.name] = StripeProvider()
        # CentralPay activates by API key alone (no separate toggle required).
        if (ps.get_str("payment.centralpay_api_key") or "").strip():
            _PROVIDERS[CentralPayProvider.name] = CentralPayProvider()


reload_providers()


def register_provider(provider: PaymentProvider) -> None:
    _PROVIDERS[provider.name] = provider


def get_provider(name: str = None) -> PaymentProvider:
    return _PROVIDERS.get(name or ManualProvider.name, _PROVIDERS[ManualProvider.name])


def available_providers(*, online_only: bool = False) -> List[str]:
    names = sorted(_PROVIDERS)
    if online_only:
        # Gateway PSPs only — exclude offline card/manual.
        return [n for n in names if n not in (ManualProvider.name, CardProvider.name)]
    return names


def gateway_providers() -> List[str]:
    return available_providers(online_only=True)


def resolve_card_for_admin(dbadmin) -> Optional[dict]:
    """Card details for this admin's portal customers.

    - Sudo / platform owner: global ``payment.card_*`` settings.
    - Reseller: only their own ``card_*`` columns — never the master's card.
    """
    if dbadmin is None:
        return None
    if getattr(dbadmin, "is_sudo", False):
        if not ps.get_bool("payment.card_enabled"):
            return None
        number = (ps.get_str("payment.card_number") or "").strip()
        if not number:
            return None
        return {
            "number": number,
            "holder": (ps.get_str("payment.card_holder") or "").strip(),
            "bank": (ps.get_str("payment.card_bank") or "").strip(),
        }
    if not bool(getattr(dbadmin, "card_enabled", False)):
        return None
    number = (getattr(dbadmin, "card_number", None) or "").strip()
    if not number:
        return None
    return {
        "number": number,
        "holder": (getattr(dbadmin, "card_holder", None) or "").strip(),
        "bank": (getattr(dbadmin, "card_bank", None) or "").strip(),
    }


def card_payment_enabled_for_admin(dbadmin=None) -> bool:
    return resolve_card_for_admin(dbadmin) is not None


def card_payment_enabled() -> bool:
    """Legacy: platform card toggle (sudo customers). Prefer card_payment_enabled_for_admin."""
    return bool(ps.get_bool("payment.card_enabled") and (ps.get_str("payment.card_number") or "").strip())


def admin_may_use_centralpay(dbadmin) -> bool:
    """Sudo always may; resellers only when centralpay_enabled is set on their row."""
    if dbadmin is None:
        return False
    if getattr(dbadmin, "is_sudo", False):
        return True
    return bool(getattr(dbadmin, "centralpay_enabled", False))


def filter_providers_for_admin(providers: List[str], dbadmin) -> List[str]:
    """Hide CentralPay unless this admin is opted in (or is sudo)."""
    if CentralPayProvider.name not in providers:
        return list(providers)
    if admin_may_use_centralpay(dbadmin):
        return list(providers)
    return [p for p in providers if p != CentralPayProvider.name]


def portal_payment_methods(dbadmin=None) -> dict:
    """Methods available on the end-user portal checkout.

    ``dbadmin`` is the reseller/owner of the portal user. CentralPay is only
    listed when that admin is opted in (or sudo) and an API key is configured.
    Card uses the owning admin's own card (reseller) or platform card (sudo).
    """
    gateway = gateway_providers() if ps.get_bool("payment.gateway_enabled") else []
    gateway = filter_providers_for_admin(gateway, dbadmin)
    card = resolve_card_for_admin(dbadmin)
    methods = []
    if gateway:
        methods.append("gateway")
    if card:
        methods.append("card")
    return {
        "methods": methods,
        "gateway_providers": gateway,
        "card": {
            "number": card["number"],
            "holder": card.get("holder") or "",
            "bank": card.get("bank") or "",
        } if card else None,
    }


def provider_supports_intent(name: str) -> bool:
    return name in _PROVIDERS and name != ManualProvider.name
