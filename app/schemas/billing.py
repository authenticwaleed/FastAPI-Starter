from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.subscription import BillingProviderName, SubscriptionStatus
from app.services.plans import Feature, PlanLimit, PlanTier


class PlanRead(BaseModel):
    """One plan, as the page that lists them shows it.

    Limits come out as a map with nulls for the unlimited ones rather
    than as absent keys: a client rendering a comparison table needs a
    row for every limit on every plan, and "not mentioned" would render
    as a gap where "unlimited" belongs.
    """

    tier: PlanTier
    name: str
    description: str
    price: Decimal
    currency: str
    features: list[Feature]
    limits: dict[PlanLimit, int | None]


class SubscriptionRead(BaseModel):
    """What a workspace is paying for."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: BillingProviderName
    plan: PlanTier
    status: SubscriptionStatus
    current_period_start: datetime | None
    current_period_end: datetime | None
    # True between somebody cancelling and the period running out. The
    # subscription is still `active` in that window because it has been
    # paid for, so this is the difference between "stopping" and
    # "stopped" -- and a dashboard that could not tell them apart would
    # say the wrong thing on both.
    cancel_at_period_end: bool
    created_at: datetime
    updated_at: datetime


class WorkspacePlan(BaseModel):
    """What a workspace may do, and what it is paying for.

    Both, because they are different questions. A `past_due` subscription
    still entitles a workspace to its plan while the provider retries, so
    a screen showing only one of these would say something untrue either
    way round.

    `subscription` is null for a workspace that has never paid, which is
    not the same as one whose payment failed -- and `plan` is what
    actually applies in both cases.
    """

    plan: PlanRead
    subscription: SubscriptionRead | None


class CheckoutRequest(BaseModel):
    """Which plan to buy."""

    plan: PlanTier


class CheckoutStarted(BaseModel):
    """Where to send the customer next.

    Nothing has changed yet. The provider's page is where a card is
    entered, and what makes the subscription real is the webhook that
    follows -- which is why this returns a URL rather than a subscription.
    """

    checkout_url: str
