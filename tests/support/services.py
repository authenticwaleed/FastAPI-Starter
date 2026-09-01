"""Assembling real services against a test's own session.

A service that reaches another service needs that other service, so
constructing one by hand in a test means constructing its graph. What
lives here is the wiring several suites would otherwise repeat -- and,
more to the point, the wiring several suites would otherwise each have to
be edited for the next time a constructor grows an argument.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.subscription import BillingProviderName, SubscriptionStatus
from app.repositories.notification_repository import NotificationRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.usage_repository import UsageRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.notification_service import NotificationService
from app.services.plans import PlanTier
from app.services.subscription_service import SubscriptionService
from app.services.usage_service import UsageService
from tests.support.billing import FakeBillingProvider


def notification_service(session: Session) -> NotificationService:
    """The real one, on a test's own session.

    Real rather than a stub. What notifications have to get right is
    landing in the same transaction as whatever caused them, and a stub
    would be a second implementation of exactly that -- one that could
    not be wrong in the way the real one can.
    """
    return NotificationService(
        session=session,
        notifications=NotificationRepository(session),
        memberships=WorkspaceMembershipRepository(session),
    )


def usage_service(session: Session) -> UsageService:
    """The meter, on a test's own session.

    Real for the same reason the notifications are. What metering has to
    get right is landing in the same transaction as the thing it meters,
    and a stub would be a second implementation of exactly that.
    """
    return UsageService(usage=UsageRepository(session))


def subscription_service(session: Session) -> SubscriptionService:
    """The capability checks, on a test's own session.

    Real, and with a provider that charges nobody. Most suites reach this
    only because a service they are testing consults it -- a workspace
    with no subscription is on the free plan, which is what those tests
    already assumed before plans existed.
    """
    return SubscriptionService(
        session=session,
        subscriptions=SubscriptionRepository(session),
        provider=FakeBillingProvider(),
        notifications=notification_service(session),
        usage=usage_service(session),
    )


def put_on_plan(
    session: Session,
    workspace_id: uuid.UUID | str,
    tier: PlanTier = PlanTier.GROWTH,
) -> None:
    """Put a workspace on a plan, without going through a checkout.

    For the suites that are about something else. Testing automations or
    a storefront means having a plan that includes them, and walking a
    payment flow to get one would make every one of those tests also a
    test of billing -- which is what tests/api/test_billing.py is for.

    Written the way a completed checkout leaves it: active, with a
    provider subscription id, because a row without one is a checkout
    somebody started and never finished.
    """
    repository = SubscriptionRepository(session)
    workspace = (
        workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(workspace_id)
    )
    subscription = repository.create(
        workspace_id=workspace,
        provider=BillingProviderName.STRIPE,
        plan=tier,
        provider_customer_id=f"cus_{workspace.hex[:12]}",
    )
    repository.apply(
        subscription,
        provider_subscription_id=f"sub_{workspace.hex[:12]}",
        status=SubscriptionStatus.ACTIVE,
    )
    session.flush()
