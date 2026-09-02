import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.staff import StaffAdminDep
from app.api.errors import (
    ADMIN_FORBIDDEN,
    ADMIN_NOT_FOUND,
    ADMIN_UNAUTHORISED,
    RATE_LIMITED,
)
from app.models.plan_override import PlanOverride
from app.models.subscription import BillingEvent, Subscription, SubscriptionStatus
from app.schemas.admin_billing import (
    AdminBillingEvent,
    AdminBillingEventPage,
    AdminSubscriptionPage,
    AdminSubscriptionRow,
    PlanOverrideRead,
    PlanOverrideRequest,
    ReplayResult,
)
from app.services.admin_billing_service import AdminBillingServiceDep
from app.services.plans import PlanTier
from app.services.subscription_service import restored

# Two prefixes, because these are two questions. The platform's ledger is
# not about any one workspace; a granted plan is about exactly one.
router = APIRouter(prefix="/billing", tags=["platform"])
override_router = APIRouter(
    prefix="/workspaces/{workspace_id}/plan-override",
    tags=["platform"],
)

PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}
NAMED = {**PLATFORM, **ADMIN_NOT_FOUND}


# `admin` throughout. Reading who is paying what is not a support
# question, and granting a plan nobody is paying for is a commercial
# decision -- neither belongs to the rank that answers tickets.
@router.get("/subscriptions", responses=PLATFORM)
def list_subscriptions(
    actor: StaffAdminDep,
    service: AdminBillingServiceDep,
    status_filter: Annotated[SubscriptionStatus | None, Query(alias="status")] = None,
    plan: Annotated[PlanTier | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminSubscriptionPage:
    """Every subscription, as the payment provider describes it.

    `status=past_due` is the filter this screen exists for: the
    businesses whose card did not go through and who still have their
    plan while the provider retries. Somebody should be looking at that
    list before those subscriptions become `unpaid`.

    Filtered on what the provider says rather than on what a workspace is
    entitled to. That is deliberate -- this is the provider's side of the
    ledger, so a business comped onto Business appears here on whatever
    it is actually paying for, and the console's workspace search is
    where the other question is asked.
    """
    found, total = service.subscriptions(
        actor,
        status=status_filter,
        plan=plan,
        page=page,
        page_size=page_size,
    )

    return AdminSubscriptionPage(
        items=[_subscription(subscription, slug) for subscription, slug in found],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/events", responses=PLATFORM)
def list_billing_events(
    actor: StaffAdminDep,
    service: AdminBillingServiceDep,
    event_type: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminBillingEventPage:
    """Deliveries from the payment provider, newest first.

    The event type is the provider's word verbatim rather than this
    application's, which is what makes a row here something you can hold
    up against the provider's own dashboard.
    """
    found, total = service.events(
        actor,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )

    return AdminBillingEventPage(
        items=[_event(event) for event in found],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/events/{event_id}/replay", responses=NAMED)
def replay_billing_event(
    event_id: uuid.UUID,
    actor: StaffAdminDep,
    service: AdminBillingServiceDep,
) -> ReplayResult:
    """Apply a stored delivery again.

    For the ones that were recorded and not acted on: a deploy
    mid-flight, a bug since fixed, a subscription that did not exist yet.

    The dedupe row is left exactly as it is. It exists to stop a provider
    *retry* being applied twice, and defeating it here would turn every
    replay into a way of losing that protection. Safe to press twice
    regardless: what gets applied is the provider's own snapshot, so
    applying it again lands on the same values.

    `applied: false` means there was nothing to do -- a delivery from
    before payloads were kept, or one naming a subscription this platform
    does not hold. Both are ordinary answers rather than errors.
    """
    return ReplayResult(applied=service.replay(actor, event_id))


@override_router.post("", status_code=status.HTTP_201_CREATED, responses=NAMED)
def grant_plan_override(
    workspace_id: uuid.UUID,
    payload: PlanOverrideRequest,
    actor: StaffAdminDep,
    service: AdminBillingServiceDep,
) -> PlanOverrideRead:
    """Put a workspace on a plan nobody is paying for.

    A pilot, a comp, an enterprise contract invoiced offline. It outranks
    the subscription and survives every webhook that follows, which is
    the whole reason it is a row of its own rather than a value written
    onto `subscriptions.plan` -- that would revert on the next delivery,
    silently.

    Replaces whatever was granted before rather than adding beside it.
    Leaving `expires_at` out is allowed and comes back with
    `forever: true`, because a grant nothing ever takes away is worth
    being told about.
    """
    return _override(
        service.grant_plan(
            actor,
            workspace_id,
            plan=payload.plan,
            reason=payload.reason,
            expires_at=payload.expires_at,
        )
    )


@override_router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NAMED,
)
def remove_plan_override(
    workspace_id: uuid.UUID,
    actor: StaffAdminDep,
    service: AdminBillingServiceDep,
) -> None:
    """Take a granted plan away, so the provider's word applies again.

    Falls back rather than down: a workspace with a live subscription
    returns to whatever the provider last said about it, and one without
    returns to free.

    Always 204. Removing a grant nobody made is not an error -- the state
    somebody wanted already holds -- and nothing is recorded for it, so
    calling this twice leaves one entry.
    """
    service.remove_plan(actor, workspace_id)


def _subscription(subscription: Subscription, slug: str) -> AdminSubscriptionRow:
    return AdminSubscriptionRow(
        id=subscription.id,
        provider=subscription.provider,
        provider_customer_id=subscription.provider_customer_id,
        provider_subscription_id=subscription.provider_subscription_id,
        plan=subscription.plan,
        status=subscription.status,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
        workspace_slug=slug,
    )


def _event(event: BillingEvent) -> AdminBillingEvent:
    return AdminBillingEvent(
        id=event.id,
        provider=event.provider,
        provider_event_id=event.provider_event_id,
        event_type=event.event_type,
        received_at=event.received_at,
        # Worked out from the payload rather than stored, so a row cannot
        # claim to be replayable and then do nothing.
        replayable=restored(event.payload) is not None,
        payload=event.payload,
    )


def _override(override: PlanOverride) -> PlanOverrideRead:
    return PlanOverrideRead(
        workspace_id=override.workspace_id,
        plan=override.plan,
        reason=override.reason,
        granted_by_user_id=override.granted_by_user_id,
        expires_at=override.expires_at,
        created_at=override.created_at,
        applies=override.applies_at(datetime.now(UTC)),
        forever=override.expires_at is None,
    )
