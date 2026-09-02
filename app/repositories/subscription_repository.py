import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models.subscription import (
    BillingEvent,
    BillingProviderName,
    Subscription,
    SubscriptionStatus,
)
from app.models.workspace import Workspace
from app.services.plans import PlanTier


class SubscriptionRepository:
    """Every query against the billing tables lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- subscriptions -----------------------------------------------------

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        provider: BillingProviderName,
        plan: PlanTier,
        provider_customer_id: str | None = None,
    ) -> Subscription:
        subscription = Subscription(
            workspace_id=workspace_id,
            provider=provider,
            plan=plan,
            provider_customer_id=provider_customer_id,
            status=SubscriptionStatus.INCOMPLETE,
        )

        self._session.add(subscription)
        self._session.flush()

        return subscription

    def get_for_workspace(self, workspace_id: uuid.UUID) -> Subscription | None:
        return self._session.scalar(
            select(Subscription).where(Subscription.workspace_id == workspace_id)
        )

    def get_by_provider_subscription_id(
        self,
        provider_subscription_id: str,
    ) -> Subscription | None:
        """The lookup a webhook costs.

        A delivery names a provider subscription and nothing else, so
        this is what turns it into a workspace -- and the reason that
        column is unique across every workspace rather than within one.
        """
        return self._session.scalar(
            select(Subscription).where(
                Subscription.provider_subscription_id == provider_subscription_id
            )
        )

    def apply(
        self,
        subscription: Subscription,
        *,
        provider_subscription_id: str | None = None,
        provider_customer_id: str | None = None,
        plan: PlanTier | None = None,
        status: SubscriptionStatus | None = None,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
        cancel_at_period_end: bool | None = None,
    ) -> Subscription:
        """Copy across what the provider said, and leave the rest.

        `None` means "the provider did not say" rather than "set this to
        null", which is the right reading here and not merely the
        convention: an event about a failed payment carries a status and
        nothing else, and treating its silence about the period as an
        instruction would erase a date the provider still believes in.
        """
        for field, value in (
            ("provider_subscription_id", provider_subscription_id),
            ("provider_customer_id", provider_customer_id),
            ("plan", plan),
            ("status", status),
            ("current_period_start", current_period_start),
            ("current_period_end", current_period_end),
            ("cancel_at_period_end", cancel_at_period_end),
        ):
            if value is not None:
                setattr(subscription, field, value)

        self._session.flush()

        return subscription

    # --- events ------------------------------------------------------------

    def record_event(
        self,
        *,
        provider: BillingProviderName,
        provider_event_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> BillingEvent:
        """Claim an event, by writing the row that says it was handled.

        Written before the work rather than after it, for the reason an
        automation run is: the unique index is the check, and an index
        only prevents anything if the claim exists before the second
        delivery looks. Raises IntegrityError on a repeat, which is what
        the caller treats as "already done".
        """
        event = BillingEvent(
            provider=provider,
            provider_event_id=provider_event_id,
            event_type=event_type,
            payload=payload or {},
        )

        self._session.add(event)
        self._session.flush()

        return event

    def get_event(self, event_id: uuid.UUID) -> BillingEvent | None:
        return self._session.get(BillingEvent, event_id)

    def list_events(
        self,
        *,
        limit: int,
        offset: int,
        event_type: str | None = None,
    ) -> Sequence[BillingEvent]:
        """Deliveries, newest first.

        Not workspace-scoped, which is unusual here and right: a delivery
        names a provider subscription and this application works out
        whose it is afterwards -- so "which deliveries have we had" is a
        question about the platform rather than about any one business.
        """
        return self._session.scalars(
            select(BillingEvent)
            .where(*_event_filters(event_type))
            .order_by(BillingEvent.received_at.desc(), BillingEvent.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_events(self, *, event_type: str | None = None) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(BillingEvent)
                .where(*_event_filters(event_type))
            )
            or 0
        )

    def list_subscriptions(
        self,
        *,
        limit: int,
        offset: int,
        status: SubscriptionStatus | None = None,
        plan: PlanTier | None = None,
    ) -> list[tuple[Subscription, str]]:
        """Every subscription on the platform, newest first, with its slug.

        `plan` filters on what the provider says rather than on what the
        workspace is entitled to, and the difference is the point of this
        screen: it is the provider's side of the ledger, and the console's
        workspace search is the other. A business comped onto Business
        appears here on whatever it is actually paying for.

        Joined to the workspace rather than looked up per row, and an
        inner join because the foreign key cascades -- a subscription
        cannot outlive its workspace. Without the slug this is a list of
        provider ids, and every other admin route is keyed on the
        workspace it would send somebody to next.
        """
        rows = self._session.execute(
            select(Subscription, Workspace.slug)
            .join(Workspace, Workspace.id == Subscription.workspace_id)
            .where(*_subscription_filters(status, plan))
            .order_by(Subscription.created_at.desc(), Subscription.id)
            .limit(limit)
            .offset(offset)
        ).all()

        return [(subscription, slug) for subscription, slug in rows]

    def count_subscriptions(
        self,
        *,
        status: SubscriptionStatus | None = None,
        plan: PlanTier | None = None,
    ) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(Subscription)
                .where(*_subscription_filters(status, plan))
            )
            or 0
        )


def _event_filters(event_type: str | None) -> list[ColumnElement[bool]]:
    """The same narrowing for a page of deliveries and its total."""
    if event_type is None:
        return []

    return [BillingEvent.event_type == event_type]


def _subscription_filters(
    status: SubscriptionStatus | None,
    plan: PlanTier | None,
) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = []

    if status is not None:
        where.append(Subscription.status == status)

    if plan is not None:
        where.append(Subscription.plan == plan)

    return where
