from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.subscription import BillingProviderName, SubscriptionStatus
from app.schemas.admin_console import AdminSubscription
from app.services.plans import PlanTier

Reason = Annotated[str, Field(min_length=10, max_length=500)]


class PlanOverrideRequest(BaseModel):
    """Putting a workspace on a plan nobody is paying for.

    `expires_at` is optional, and leaving it out is warned about rather
    than refused -- the plan's own instruction, and the honest
    compromise. A comp somebody negotiated has no natural end, so
    requiring a date would mean inventing one; and a grant with no date
    is a plan nothing ever takes away, which is worth being told about
    rather than discovering two years later on a revenue report.

    The warning is `forever` on the response beside it, which a console
    can render in amber. Refusing here would be wrong, and accepting
    silently would be the thing the plan asks to avoid.
    """

    plan: PlanTier
    reason: Reason
    expires_at: datetime | None = None


class PlanOverrideRead(BaseModel):
    """A granted plan, and whether it is actually in force."""

    workspace_id: UUID
    plan: PlanTier
    reason: str
    granted_by_user_id: int | None
    expires_at: datetime | None
    created_at: datetime
    # Computed from `expires_at` and the clock, like every other liveness
    # on this surface. An expired grant is kept and shown, because "this
    # was comped until March" is the answer to why a customer remembers
    # having a feature they no longer have.
    applies: bool
    # True where no date was set. The plan asks for a warning rather than
    # a refusal, and this is it: something a console can render in
    # amber next to a grant nothing will ever take away.
    forever: bool


class AdminSubscriptionRow(AdminSubscription):
    """One subscription, with the workspace it belongs to named.

    A list of subscriptions without workspaces is a list of provider ids.
    The slug is here so a row can be acted on -- every other admin route
    is keyed on the workspace, and this is the screen somebody arrives at
    before using one of them.
    """

    workspace_slug: str | None


class AdminSubscriptionPage(BaseModel):
    items: list[AdminSubscriptionRow]
    total: int
    page: int
    page_size: int


class AdminBillingEvent(BaseModel):
    """One delivery from the payment provider.

    `replayable` is false for the deliveries recorded before payloads
    were kept. Saying so is better than a replay button that answers
    "nothing happened" -- there is genuinely nothing to re-apply, and
    reconstructing one from the subscription's current state would replay
    something the provider never sent.
    """

    id: UUID
    provider: BillingProviderName
    provider_event_id: str
    event_type: str
    received_at: datetime
    replayable: bool
    # The delivery in this application's words, which is what a replay
    # would apply. Never the raw body: that is the provider's to keep and
    # carries fields nothing here reads.
    payload: dict[str, Any]


class AdminBillingEventPage(BaseModel):
    items: list[AdminBillingEvent]
    total: int
    page: int
    page_size: int


class ReplayResult(BaseModel):
    """What a replay did.

    `applied` is false where the delivery had no payload to re-apply or
    named a subscription this platform does not hold. Both are ordinary
    answers rather than errors, and both are worth telling somebody who
    just pressed a button expecting a change.
    """

    applied: bool


class AdminEntitlement(BaseModel):
    """What a workspace may do, and where that came from.

    Three fields because there are three sources and the interesting case
    is when they disagree: a business on `past_due` still entitled to
    Growth, or one comped onto Business while the provider says Starter.
    A screen showing only the resolved plan could not explain either.
    """

    plan: PlanTier
    subscription_status: SubscriptionStatus | None
    override: PlanOverrideRead | None
