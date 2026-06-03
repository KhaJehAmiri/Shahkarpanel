"""Payment provider abstraction.

Providers translate an invoice into a payment intent and verify completion.
Phase 3 ships a manual provider (an admin confirms payment); real gateways
(Stripe, crypto, local PSPs) can be added as plugins behind the same contract.
"""
from typing import Dict, List


class PaymentProvider:
    name = "base"

    def create_payment(self, invoice) -> dict:
        """Return payment instructions / a redirect for the given invoice."""
        raise NotImplementedError

    def verify(self, invoice, payload: dict) -> bool:
        """Verify a callback/confirmation for the invoice."""
        raise NotImplementedError


class ManualProvider(PaymentProvider):
    name = "manual"

    def create_payment(self, invoice) -> dict:
        return {
            "provider": self.name,
            "amount": invoice.amount,
            "instructions": "Pay out-of-band; a sudo admin will confirm the invoice.",
        }

    def verify(self, invoice, payload: dict) -> bool:
        # Manual confirmation is performed by an admin, so this always succeeds.
        return True


_PROVIDERS: Dict[str, PaymentProvider] = {ManualProvider.name: ManualProvider()}


def register_provider(provider: PaymentProvider) -> None:
    _PROVIDERS[provider.name] = provider


def get_provider(name: str = None) -> PaymentProvider:
    return _PROVIDERS.get(name or ManualProvider.name, _PROVIDERS[ManualProvider.name])


def available_providers() -> List[str]:
    return sorted(_PROVIDERS)
