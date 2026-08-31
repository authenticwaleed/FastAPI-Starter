import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column
from app.services.plans import PlanTier


class BillingProviderName(StrEnum):
    """Who takes the money.

    One value. Stripe is what the MVP charges through; the column exists
    rather than the assumption because a business selling in Pakistan may
    well need a local processor before it needs a second storefront.
    """

    STRIPE = "stripe"


class SubscriptionStatus(StrEnum):
    """Where a subscription stands, in the provider's vocabulary.

    Kept as the provider says it rather than reduced to "working / not
    working", because the difference between them is the whole of how a
    billing failure is handled. `past_due` is a card that did not go
    through and a provider that is still retrying; treating it the same
    as `canceled` would take a business's automations away over a bank's
    fraud check, which is the wrong way to lose a customer.
    """

    # Paid and current, or in a trial. Both mean "use the plan".
    ACTIVE = "active"
    TRIALING = "trialing"
    # Payment failed and the provider has not given up. The plan still
    # applies -- see SubscriptionService.plan_for -- and somebody is told.
    PAST_DUE = "past_due"
    # The provider has given up, or the customer has stopped. Neither is
    # the plan any more.
    UNPAID = "unpaid"
    CANCELED = "canceled"
    # Checkout was started and never finished. Not a plan either.
    INCOMPLETE = "incomplete"


class Subscription(Base):
    """What one workspace is paying for, and what the provider says about it.

    Only ever written from the provider. A checkout starts one there and a
    webhook brings the answer back, which is why every field below is a
    copy rather than a decision: the provider owns whether a subscription
    is current, and a row here that disagreed with it would be a workspace
    using a plan nobody is paying for.
    """

    __tablename__ = "subscriptions"

    __table_args__ = (
        # One per workspace, which is what makes "the workspace's plan" a
        # thing that can be spoken about in the singular.
        UniqueConstraint("workspace_id", name="uq_subscriptions_workspace_id"),
        # The lookup a webhook costs: a delivery names a provider
        # subscription and nothing else, so this is what turns it into a
        # workspace. Unique across all of them for the same reason a shop
        # domain is.
        UniqueConstraint(
            "provider_subscription_id",
            name="uq_subscriptions_provider_subscription_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    provider: Mapped[BillingProviderName] = mapped_column(
        enum_column(BillingProviderName, name="billing_provider"),
    )

    # The provider's customer, which outlives any one subscription: a
    # business that cancels and comes back should not become a second
    # customer with a second billing history.
    provider_customer_id: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
    )

    # Null between starting a checkout and the provider telling us it
    # completed. A row exists in that gap so the customer id is not lost.
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
    )

    plan: Mapped[PlanTier] = mapped_column(
        enum_column(PlanTier, name="plan_tier"),
        default=PlanTier.STARTER,
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_column(SubscriptionStatus, name="subscription_status"),
        default=SubscriptionStatus.INCOMPLETE,
    )

    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # Set when somebody cancels. The subscription stays `active` until the
    # period runs out, because they have paid for it -- so this is the
    # difference between "stopping" and "stopped", and a dashboard that
    # could not tell them apart would say the wrong thing on both.
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"Subscription(id={self.id!r}, plan={self.plan!r})"


class BillingEvent(Base):
    """One delivery from the payment provider, recorded so it is not acted on twice.

    Billing webhooks are the one place in this application where handling
    a delivery twice is not merely untidy. A provider retries whatever it
    did not get a prompt 200 for, and the events it sends are not all
    idempotent to apply -- and unlike a product sync, the thing being got
    wrong is what somebody is charged for and what they are allowed to
    use.

    So the id goes in first and the work happens after. The unique index
    is the check; a second delivery of the same event loses at the insert
    rather than halfway through changing a plan.
    """

    __tablename__ = "billing_events"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_billing_events_provider_provider_event_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    provider: Mapped[BillingProviderName] = mapped_column(
        enum_column(BillingProviderName, name="billing_event_provider"),
    )

    provider_event_id: Mapped[str] = mapped_column(String(255))

    # What the provider called it, verbatim. Not this application's
    # vocabulary, because the useful thing about this column is being
    # able to hold it up against the provider's own dashboard.
    event_type: Mapped[str] = mapped_column(String(120))

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"BillingEvent(provider_event_id={self.provider_event_id!r})"
