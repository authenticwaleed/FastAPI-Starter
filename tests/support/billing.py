"""A payment provider that charges nobody.

Substituted wherever a test needs a subscription to exist, change or
lapse. No test in this suite reaches Stripe.

`verify_webhook` and `parse_webhook` delegate to the real adapter, for the
reason every other fake here delegates its pure half: checking a signature
and reading a provider's payload shape are the parts most worth testing
against the code that will actually run, and neither opens a socket.
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.exceptions import BillingProviderError
from app.integrations.billing.base import (
    BillingEventPayload,
    Checkout,
    RemoteSubscription,
)
from app.integrations.billing.stripe import StripeProvider
from app.models.subscription import BillingProviderName, SubscriptionStatus
from app.services.plans import PlanTier


@dataclass
class FakeBillingProvider:
    """Hands back a checkout URL, and remembers what it was asked."""

    checkout_url: str = "https://checkout.example/session/abc"
    customer_id: str = "cus_FAKE"
    subscription_id: str = "sub_FAKE"
    checkouts: list[tuple[PlanTier, str | None]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    fail_with: str | None = None

    @property
    def name(self) -> BillingProviderName:
        return BillingProviderName.STRIPE

    def start_checkout(
        self,
        *,
        plan: PlanTier,
        workspace_id: str,
        customer_id: str | None,
        success_url: str,
        cancel_url: str,
    ) -> Checkout:
        self.checkouts.append((plan, customer_id))

        if self.fail_with is not None:
            raise BillingProviderError(self.fail_with)

        return Checkout(url=self.checkout_url, provider_customer_id=self.customer_id)

    def cancel(self, *, provider_subscription_id: str) -> RemoteSubscription:
        self.cancelled.append(provider_subscription_id)

        if self.fail_with is not None:
            raise BillingProviderError(self.fail_with)

        return RemoteSubscription(
            provider_subscription_id=provider_subscription_id,
            provider_customer_id=self.customer_id,
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
            current_period_end=datetime.now(UTC) + timedelta(days=20),
        )

    def verify_webhook(self, *, payload: bytes, signature: str | None) -> bool:
        return StripeProvider().verify_webhook(payload=payload, signature=signature)

    def parse_webhook(self, payload: dict[str, Any]) -> BillingEventPayload:
        """Read the delivery for real, but never fetch anything.

        The one place the real adapter would reach the network is a
        completed checkout, which it follows up by fetching the
        subscription. Here the event carries the subscription outright,
        which is the shape every other Stripe event already has.
        """
        return StripeProvider().parse_webhook(payload)


def subscription_event(
    *,
    event_id: str = "evt_1",
    event_type: str = "customer.subscription.updated",
    subscription_id: str = "sub_FAKE",
    customer_id: str = "cus_FAKE",
    plan: PlanTier = PlanTier.GROWTH,
    status: str = "active",
    cancel_at_period_end: bool = False,
) -> dict[str, Any]:
    """An event shaped the way Stripe actually sends one."""
    now = int(time.time())

    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": subscription_id,
                "customer": customer_id,
                "status": status,
                "cancel_at_period_end": cancel_at_period_end,
                "current_period_start": now,
                "current_period_end": now + 30 * 24 * 3600,
                "metadata": {"plan": plan.value},
            }
        },
    }


def invoice_failed_event(
    *,
    event_id: str = "evt_failed",
    subscription_id: str = "sub_FAKE",
    customer_id: str = "cus_FAKE",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "in_1",
                "subscription": subscription_id,
                "customer": customer_id,
            }
        },
    }
