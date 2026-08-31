"""What this application needs of whoever takes the money.

Three things, and no more: somewhere to send a customer to pay, a way to
stop a subscription, and a way to understand what the provider says
afterwards. Everything provider-shaped stops here -- price identifiers,
the shape of a webhook signature, the vocabulary of statuses -- and what
leaves is this module's words.

Stripe is what the MVP charges through. The reason this is a Protocol
rather than a Stripe client with a nicer name is the same reason it is
one for messaging: a business selling in Pakistan may well need a local
processor before it needs a second storefront, and that should be an
adapter rather than a rewrite.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from app.models.subscription import BillingProviderName, SubscriptionStatus
from app.services.plans import PlanTier


class BillingEventKind(StrEnum):
    """The kinds of change worth acting on, in this application's words.

    A provider's own event names are translated by the adapter. Anything
    it sends that is not one of these is acknowledged and ignored: a
    webhook subscription is easy to widen by accident, and a delivery
    that cannot be handled must not be retried for a day.
    """

    # A checkout finished, or a subscription changed: its plan, its
    # period, its status. One kind rather than three, because what this
    # application does with all of them is identical -- copy what the
    # provider says.
    SUBSCRIPTION_UPDATED = "subscription_updated"
    # It is over. Whatever the reason, the workspace falls back.
    SUBSCRIPTION_ENDED = "subscription_ended"
    # A payment did not go through and the provider is still trying.
    PAYMENT_FAILED = "payment_failed"


@dataclass(frozen=True)
class Checkout:
    """Where to send somebody to pay, and who they are to the provider."""

    url: str
    provider_customer_id: str | None = None


@dataclass(frozen=True)
class RemoteSubscription:
    """A subscription as the provider describes it, in this app's words."""

    provider_subscription_id: str
    provider_customer_id: str | None = None
    plan: PlanTier | None = None
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


@dataclass(frozen=True)
class BillingEventPayload:
    """One delivery, sorted into something the service can act on.

    `event_id` is the whole point of this being a value rather than a
    dict: it is what makes handling a delivery twice impossible, and a
    shape that could omit it would let somebody forget.
    """

    event_id: str
    event_type: str
    kind: BillingEventKind | None
    subscription: RemoteSubscription | None = None


class BillingProvider(Protocol):
    """Starting a subscription, stopping one, and reading what happened."""

    @property
    def name(self) -> BillingProviderName: ...

    def start_checkout(
        self,
        *,
        plan: PlanTier,
        workspace_id: str,
        customer_id: str | None,
        success_url: str,
        cancel_url: str,
    ) -> Checkout:
        """Somewhere to send a customer to pay.

        Raises BillingProviderError if the provider refuses, or if this
        plan has no price configured -- which is a deployment that cannot
        sell it, not a customer who cannot buy it.
        """
        ...

    def cancel(self, *, provider_subscription_id: str) -> RemoteSubscription:
        """Stop it at the end of the period that has been paid for.

        Not immediately, and that is not the provider's choice: somebody
        who has paid for a month is entitled to the month.
        """
        ...

    def verify_webhook(self, *, payload: bytes, signature: str | None) -> bool: ...

    def parse_webhook(self, payload: dict[str, Any]) -> BillingEventPayload:
        """Turn one delivery into something the service understands."""
        ...
