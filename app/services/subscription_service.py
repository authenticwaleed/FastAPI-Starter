import logging
import uuid
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    BillingProviderError,
    FeatureNotInPlanError,
    NoSubscriptionError,
    PlanLimitReachedError,
)
from app.db.session import SessionDep
from app.integrations.billing.base import (
    BillingEventKind,
    BillingEventPayload,
    BillingProvider,
    Checkout,
)
from app.integrations.billing.stripe import StripeProvider
from app.models.audit_log import AuditEvent
from app.models.notification import NotificationKind
from app.models.subscription import Subscription, SubscriptionStatus
from app.repositories.subscription_repository import SubscriptionRepository
from app.services.audit_service import AuditService, AuditServiceDep
from app.services.notification_service import (
    NotificationService,
    NotificationServiceDep,
)
from app.services.plans import (
    FREE_PLAN,
    PLANS,
    Feature,
    Plan,
    PlanLimit,
    PlanTier,
)
from app.services.usage_service import (
    LIMIT_METRICS,
    UsageService,
    UsageServiceDep,
)
from app.services.workspace_service import MAY_ADMINISTER, WorkspaceAccess

logger = logging.getLogger(__name__)

# The statuses under which a workspace actually gets what it pays for.
# Public rather than private since the platform console arrived: it has to
# ask the same question in SQL, across every workspace at once, and two
# definitions of "is this subscription good for anything" would be two
# answers the day somebody edited one of them.
#
# `past_due` is in here deliberately: a card that did not go through is a
# provider still retrying, and taking a business's automations away over a
# bank's fraud check is the wrong way to lose a customer. What happens
# instead is that its administrators are told.
ENTITLING = frozenset(
    {
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.TRIALING,
        SubscriptionStatus.PAST_DUE,
    }
)


@lru_cache
def get_billing_provider() -> BillingProvider:
    """Whoever takes the money, as a dependency.

    A dependency and not an import, so a test substitutes one that
    charges nobody. Cached because the adapter holds only configuration.
    """
    return StripeProvider()


BillingProviderDep = Annotated[BillingProvider, Depends(get_billing_provider)]


class SubscriptionService:
    """What a workspace is on, and what that lets it do.

    The plan's instruction for this phase, as a class: do not hard-code
    plan checks around the codebase, create centralised capability
    checks. Every question about what a workspace may do is answered
    here, from one plan catalogue, and a route asks by declaring it
    rather than by writing an `if`.

    Everything about the subscription itself is copied from the provider
    and never decided here. A row that disagreed with the provider would
    be a workspace using a plan nobody is paying for, or paying for one
    it cannot use.
    """

    def __init__(
        self,
        session: Session,
        subscriptions: SubscriptionRepository,
        provider: BillingProvider,
        notifications: NotificationService,
        usage: UsageService,
        audit: AuditService,
    ) -> None:
        self._session = session
        self._subscriptions = subscriptions
        self._provider = provider
        self._notifications = notifications
        self._usage = usage
        self._audit = audit

    # --- what a workspace may do -------------------------------------------

    def plan_for(self, workspace_id: uuid.UUID) -> Plan:
        """The plan a workspace is actually entitled to right now.

        Not the plan it subscribed to: the plan it subscribed to *while
        that subscription is good for something*. A cancelled or unpaid
        subscription falls back to the free plan rather than to nothing,
        which is what stops a declined card locking a business out of its
        own inbox.
        """
        subscription = self._subscriptions.get_for_workspace(workspace_id)

        if subscription is None or subscription.status not in ENTITLING:
            return FREE_PLAN

        return PLANS[subscription.plan]

    def require_feature(self, workspace_id: uuid.UUID, feature: Feature) -> None:
        """Refuse unless this workspace's plan includes it.

        The one function every feature gate goes through. Routes reach it
        through the dependency in app/api/dependencies/plan.py, so what a
        plan admits is declared in a signature and cannot be forgotten by
        omission in the route somebody adds next month.
        """
        if not self.plan_for(workspace_id).admits(feature):
            raise FeatureNotInPlanError(workspace_id, feature.value)

    def require_within_limit(
        self,
        workspace_id: uuid.UUID,
        limit: PlanLimit,
    ) -> None:
        """Refuse if this workspace already has as many as it may.

        Read from the meter rather than counted here, which is the point
        of the usage phase: the number that refuses a business is the same
        number its usage page shows it. Two queries that agreed by
        coincidence were what made the previous arrangement fragile --
        the AI allowance was counted from the decision log, which has a
        row for every time the assistant declined to answer.
        """
        ceiling = self.plan_for(workspace_id).ceiling(limit)

        if ceiling is None:
            return

        used = self._usage.measure(workspace_id, LIMIT_METRICS[limit])

        if used >= ceiling:
            raise PlanLimitReachedError(workspace_id, limit.value, ceiling)

    # --- selling -----------------------------------------------------------

    def read(self, access: WorkspaceAccess) -> tuple[Subscription | None, Plan]:
        """What this workspace is paying for, and what it may do.

        Both, because they are different questions and a dashboard needs
        both answers: a subscription that is `past_due` still entitles a
        workspace to its plan, and a screen showing only one of those
        would say something untrue either way round.
        """
        return (
            self._subscriptions.get_for_workspace(access.workspace.id),
            self.plan_for(access.workspace.id),
        )

    def start_checkout(self, access: WorkspaceAccess, plan: PlanTier) -> Checkout:
        """Somewhere to send somebody to pay.

        Nothing changes here. A row is written to hold the provider's
        customer id so that a business which cancels and comes back is
        the same customer, and everything else waits for the provider to
        say the checkout completed.
        """
        workspace_id = access.workspace.id

        if PLANS[plan].is_free:
            # There is nothing to check out. Cancelling is how somebody
            # goes back to the free plan, and pretending otherwise would
            # send them to a payment page for nothing.
            raise BillingProviderError(f"{PLANS[plan].name} is not a paid plan")

        subscription = self._subscriptions.get_for_workspace(workspace_id)
        settings = get_settings()
        base = (settings.frontend_base_url or "").rstrip("/")

        checkout = self._provider.start_checkout(
            plan=plan,
            workspace_id=str(workspace_id),
            customer_id=(subscription.provider_customer_id if subscription else None),
            success_url=f"{base}/billing/done",
            cancel_url=f"{base}/billing",
        )

        if subscription is None:
            subscription = self._subscriptions.create(
                workspace_id=workspace_id,
                provider=self._provider.name,
                plan=plan,
                provider_customer_id=checkout.provider_customer_id,
            )
        else:
            self._subscriptions.apply(
                subscription,
                provider_customer_id=checkout.provider_customer_id,
            )

        self._session.commit()

        return checkout

    def cancel(self, access: WorkspaceAccess) -> Subscription:
        """Stop at the end of the period that has been paid for.

        Not immediately, and the provider is told rather than asked: the
        row here is a copy, so what makes a cancellation real is the
        provider agreeing to it. What comes back is applied straight
        away so a dashboard does not have to wait for a webhook to show
        the right thing.
        """
        workspace_id = access.workspace.id
        subscription = self._subscriptions.get_for_workspace(workspace_id)

        if subscription is None or subscription.provider_subscription_id is None:
            raise NoSubscriptionError(workspace_id)

        remote = self._provider.cancel(
            provider_subscription_id=subscription.provider_subscription_id,
        )

        self._subscriptions.apply(
            subscription,
            status=remote.status,
            cancel_at_period_end=remote.cancel_at_period_end,
            current_period_end=remote.current_period_end,
        )
        # With a person on it, unlike the webhook's echo of the same
        # change a moment later. Who stopped paying for the product is a
        # question a business asks about itself, and the provider's
        # delivery cannot answer it.
        self._audit.did(
            workspace_id,
            AuditEvent.SUBSCRIPTION_CHANGED,
            actor_user_id=access.membership.user_id,
            meta={
                "plan": subscription.plan.value,
                "status": subscription.status.value,
                "cancel_at_period_end": subscription.cancel_at_period_end,
            },
        )
        self._session.commit()

        return subscription

    # --- listening ---------------------------------------------------------

    def apply_event(self, event: BillingEventPayload) -> bool:
        """Bring the provider's word back, once.

        Returns whether this delivery did anything -- False for one
        already handled and for a topic nothing acts on, both of which
        the route answers 200 to.

        The claim comes first and the work second. A provider retries
        whatever it did not get a prompt 200 for, and unlike a product
        sync the thing being got wrong here is what somebody is charged
        and what they are allowed to use.
        """
        if event.kind is None or not event.event_id:
            return False

        try:
            self._subscriptions.record_event(
                provider=self._provider.name,
                provider_event_id=event.event_id,
                event_type=event.event_type,
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            logger.info("Billing event %s has already been handled", event.event_id)

            return False

        remote = event.subscription

        if remote is None:
            return False

        subscription = self._subscriptions.get_by_provider_subscription_id(
            remote.provider_subscription_id
        )

        if subscription is None and remote.provider_customer_id is not None:
            # The first event after a checkout: the row exists, written
            # when the checkout started, but has no provider subscription
            # id on it yet. Found by the customer instead.
            subscription = self._by_customer(remote.provider_customer_id)

        if subscription is None:
            # A subscription nothing here holds. Acknowledged rather than
            # refused: the delivery is real, it is simply not ours, and a
            # non-200 would have the provider retry it for a day.
            logger.info("A billing event named a subscription we do not hold")

            return False

        status = (
            SubscriptionStatus.CANCELED
            if event.kind is BillingEventKind.SUBSCRIPTION_ENDED
            else remote.status
        )
        before = (subscription.plan, subscription.status)

        self._subscriptions.apply(
            subscription,
            provider_subscription_id=remote.provider_subscription_id,
            provider_customer_id=remote.provider_customer_id,
            plan=remote.plan,
            status=status,
            current_period_start=remote.current_period_start,
            current_period_end=remote.current_period_end,
            cancel_at_period_end=remote.cancel_at_period_end,
        )

        if before != (subscription.plan, subscription.status):
            # No actor: a payment provider changed this, and naming
            # somebody would put an accusation in the record. Recorded
            # only where the plan or the status actually moved, because a
            # provider sends several events about one change and an audit
            # log that repeats itself is one nobody reads.
            self._audit.did(
                subscription.workspace_id,
                AuditEvent.SUBSCRIPTION_CHANGED,
                meta={
                    "plan": {"from": before[0].value, "to": subscription.plan.value},
                    "status": {
                        "from": before[1].value,
                        "to": subscription.status.value,
                    },
                    "event_type": event.event_type,
                },
            )

        if status in {SubscriptionStatus.PAST_DUE, SubscriptionStatus.UNPAID}:
            # Told rather than switched off. The plan still applies while
            # the provider is retrying, and what a business needs is
            # somebody noticing before it stops applying.
            self._notifications.tell_everyone(
                workspace_id=subscription.workspace_id,
                roles=MAY_ADMINISTER,
                kind=NotificationKind.BILLING_PAYMENT_FAILED,
                title="A payment did not go through",
                body="Update the card on file to keep your plan.",
            )

        self._session.commit()

        return True

    def _by_customer(self, provider_customer_id: str) -> Subscription | None:
        return self._session.scalar(
            select(Subscription).where(
                Subscription.provider_customer_id == provider_customer_id
            )
        )


def get_subscription_repository(session: SessionDep) -> SubscriptionRepository:
    return SubscriptionRepository(session)


SubscriptionRepositoryDep = Annotated[
    SubscriptionRepository,
    Depends(get_subscription_repository),
]


def get_subscription_service(
    session: SessionDep,
    subscriptions: SubscriptionRepositoryDep,
    provider: BillingProviderDep,
    notifications: NotificationServiceDep,
    usage: UsageServiceDep,
    audit: AuditServiceDep,
) -> SubscriptionService:
    return SubscriptionService(
        session=session,
        subscriptions=subscriptions,
        provider=provider,
        notifications=notifications,
        usage=usage,
        audit=audit,
    )


SubscriptionServiceDep = Annotated[
    SubscriptionService,
    Depends(get_subscription_service),
]
