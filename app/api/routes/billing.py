from fastapi import APIRouter, status

from app.api.dependencies.workspace import WorkspaceAdminDep, WorkspaceMemberDep
from app.api.errors import (
    NO_SUBSCRIPTION,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.subscription import Subscription
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutStarted,
    PlanRead,
    SubscriptionRead,
    WorkspacePlan,
)
from app.services.plans import PLANS, Plan
from app.services.subscription_service import SubscriptionServiceDep

# The catalogue is public and workspace-independent: it is a price list,
# and somebody deciding whether to sign up has no workspace yet.
plans_router = APIRouter(prefix="/plans", tags=["billing"])

router = APIRouter(
    prefix="/workspaces/{workspace_id}/subscription",
    tags=["billing"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


def _plan(plan: Plan) -> PlanRead:
    return PlanRead(
        tier=plan.tier,
        name=plan.name,
        description=plan.description,
        price=plan.price,
        currency=plan.currency,
        features=sorted(plan.features),
        limits=dict(plan.limits),
    )


@plans_router.get("")
def list_plans() -> list[PlanRead]:
    """Every plan, in the order they grow.

    Unauthenticated, because a price list is a price list: whoever is
    deciding whether to sign up does not have an account yet, and asking
    them to make one to see what it costs is the wrong way round.

    Read from the catalogue in `app/services/plans.py` rather than from a
    table, which is the plan's instruction for this phase -- what a plan
    admits is code, so this endpoint and every capability check answer
    from the same place and cannot drift.
    """
    return [_plan(plan) for plan in PLANS.values()]


@router.get("", responses=SCOPED)
def read_subscription(
    access: WorkspaceMemberDep,
    service: SubscriptionServiceDep,
) -> WorkspacePlan:
    """What this workspace may do, and what it is paying for.

    Any member, not just an administrator: what the business is on
    governs what everybody working in it can do, and being told "your
    plan does not include this" by a screen that will not say what the
    plan is would be a dead end.
    """
    subscription, plan = service.read(access)

    return WorkspacePlan(plan=_plan(plan), subscription=_subscription(subscription))


@router.post(
    "/checkout",
    status_code=status.HTTP_200_OK,
    responses=SCOPED,
)
def start_checkout(
    payload: CheckoutRequest,
    access: WorkspaceAdminDep,
    service: SubscriptionServiceDep,
) -> CheckoutStarted:
    """Somewhere to send somebody to pay.

    Nothing changes here, and that is the design rather than a
    limitation: the card is entered on the provider's own page, and what
    makes a subscription real is the webhook that follows. A client
    redirects to this URL and waits to be told.
    """
    checkout = service.start_checkout(access, payload.plan)

    return CheckoutStarted(checkout_url=checkout.url)


@router.post(
    "/cancel",
    responses={**SCOPED, **NO_SUBSCRIPTION},
)
def cancel_subscription(
    access: WorkspaceAdminDep,
    service: SubscriptionServiceDep,
) -> SubscriptionRead:
    """Stop at the end of the period that has been paid for.

    Not immediately. Somebody who has paid for a month is entitled to the
    month, so this sets the subscription to end rather than ending it --
    and until it does, everything keeps working.
    """
    return SubscriptionRead.model_validate(service.cancel(access))


def _subscription(subscription: Subscription | None) -> SubscriptionRead | None:
    if subscription is None:
        return None

    return SubscriptionRead.model_validate(subscription)
