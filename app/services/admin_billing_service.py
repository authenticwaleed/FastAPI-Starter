"""Reading what the provider says, and granting what it does not know about.

Phase A5, and the boundary is stated in the plan and worth repeating
here: **this surface reads billing and grants entitlements; it does not
move money.** Refunds and invoice corrections stay in the payment
provider's dashboard, which is better at them and is already the system
of record. What this adds is the two things that dashboard cannot do --
grant a plan nobody is paying for, and re-apply a delivery that was
recorded and not acted on.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import BillingProviderError, WorkspaceNotFoundError
from app.db.session import SessionDep
from app.models.admin_audit_log import AdminAction
from app.models.plan_override import PlanOverride
from app.models.subscription import BillingEvent, Subscription, SubscriptionStatus
from app.repositories.admin_console_repository import (
    AdminConsoleRepository,
    WorkspaceRow,
)
from app.repositories.plan_override_repository import PlanOverrideRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.services.admin_audit_service import AdminAuditService, AdminAuditServiceDep
from app.services.admin_workspace_service import AdminConsoleRepositoryDep
from app.services.plans import PlanTier
from app.services.staff_service import StaffActor
from app.services.subscription_service import (
    PlanOverrideRepositoryDep,
    SubscriptionRepositoryDep,
    SubscriptionService,
    SubscriptionServiceDep,
    restored,
)


class AdminBillingService:
    """The provider's ledger, and the platform's own grants beside it."""

    def __init__(
        self,
        session: Session,
        console: AdminConsoleRepository,
        subscriptions: SubscriptionRepository,
        overrides: PlanOverrideRepository,
        billing: SubscriptionService,
        admin_audit: AdminAuditService,
    ) -> None:
        self._session = session
        self._console = console
        self._subscriptions = subscriptions
        self._overrides = overrides
        self._billing = billing
        self._admin_audit = admin_audit

    # --- the provider's side ----------------------------------------------

    def subscriptions(
        self,
        actor: StaffActor,
        *,
        status: SubscriptionStatus | None = None,
        plan: PlanTier | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[Sequence[Subscription], int]:
        """Every subscription, filtered by what the provider says.

        `past_due` is the filter this screen exists for: it is the list of
        businesses whose card did not go through and who are still
        entitled to their plan while the provider retries. Somebody
        should be looking at it before those subscriptions become
        `unpaid`.
        """
        found = self._subscriptions.list_subscriptions(
            limit=page_size,
            offset=(page - 1) * page_size,
            status=status,
            plan=plan,
        )
        total = self._subscriptions.count_subscriptions(status=status, plan=plan)

        self._admin_audit.did(
            actor.logged,
            AdminAction.SUBSCRIPTIONS_SEARCHED,
            meta={
                "status": status.value if status else None,
                "plan": plan.value if plan else None,
                "results": total,
            },
        )
        self._session.commit()

        return found, total

    def events(
        self,
        actor: StaffActor,
        *,
        event_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[Sequence[BillingEvent], int]:
        """Deliveries from the provider, newest first."""
        found = self._subscriptions.list_events(
            limit=page_size,
            offset=(page - 1) * page_size,
            event_type=event_type,
        )
        total = self._subscriptions.count_events(event_type=event_type)

        self._admin_audit.did(
            actor.logged,
            AdminAction.BILLING_EVENTS_READ,
            meta={"event_type": event_type, "results": total},
        )
        self._session.commit()

        return found, total

    def replay(self, actor: StaffActor, event_id: uuid.UUID) -> bool:
        """Apply a stored delivery again.

        For the deliveries that were recorded and not acted on -- a
        deploy mid-flight, a bug since fixed, a subscription that did not
        exist yet. The claim row is left exactly as it is: the dedupe
        exists to stop a provider *retry* being applied twice, and
        defeating it here would turn every replay into a way of losing
        that protection.

        Idempotent, and not by a guard here. What is applied is the
        provider's own snapshot, so applying it twice lands on the same
        values -- which is what makes replaying an already-processed
        event safe rather than merely permitted.

        Returns whether anything moved. False for a delivery from before
        payloads were kept, and for one naming no subscription: the
        console says so rather than reporting a replay that did nothing.
        """
        event = self._subscriptions.get_event(event_id)

        if event is None:
            raise BillingProviderError(f"No billing event with id {event_id}")

        stored = restored(event.payload)
        applied = False if stored is None else self._billing.apply_remote(stored)

        self._admin_audit.did(
            actor.logged,
            AdminAction.BILLING_EVENT_REPLAYED,
            meta={
                "billing_event_id": str(event.id),
                "provider_event_id": event.provider_event_id,
                "event_type": event.event_type,
                "applied": applied,
            },
        )
        self._session.commit()

        return applied

    # --- the platform's own grants ----------------------------------------

    def grant_plan(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        *,
        plan: PlanTier,
        reason: str,
        expires_at: datetime | None,
    ) -> PlanOverride:
        """Put a workspace on a plan nobody is paying for.

        Replaces whatever was granted before rather than adding beside
        it, so "the granted plan" stays something that can be spoken
        about in the singular.

        Nothing is written to the customer's own audit log. A comp is a
        commercial arrangement between the business and whoever sold to
        them, not an act on their account -- and an entry saying the
        platform changed their plan, when what changed is that they stop
        being charged for it, would raise a question rather than answer
        one.
        """
        row = self._workspace(workspace_id)
        override = self._overrides.upsert(
            workspace_id=workspace_id,
            plan=plan,
            reason=reason,
            granted_by_user_id=actor.user.id,
            expires_at=expires_at,
        )

        self._record(
            actor,
            AdminAction.PLAN_OVERRIDE_GRANTED,
            row,
            {
                "plan": plan.value,
                "reason": reason,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )

        return override

    def remove_plan(self, actor: StaffActor, workspace_id: uuid.UUID) -> bool:
        """Take a granted plan away, so the provider's word applies again.

        Falls back rather than down: a workspace with a live subscription
        returns to whatever the provider last said about it, and one
        without returns to free. Removing a grant nobody made is not an
        error -- the desired state already holds -- and it records
        nothing, so calling it twice leaves one entry.
        """
        row = self._workspace(workspace_id)
        override = self._overrides.get_for_workspace(workspace_id)

        if override is None:
            return False

        was = override.plan

        self._overrides.delete(override)
        self._record(
            actor,
            AdminAction.PLAN_OVERRIDE_REMOVED,
            row,
            {"plan": was.value},
        )

        return True

    def override_for(self, workspace_id: uuid.UUID) -> PlanOverride | None:
        """The grant on this workspace, in force or not.

        Not audited, because nothing reads it on its own: it is what the
        workspace detail and the grant routes render alongside a read
        that was already recorded.
        """
        return self._overrides.get_for_workspace(workspace_id)

    # --- shared ------------------------------------------------------------

    def _workspace(self, workspace_id: uuid.UUID) -> WorkspaceRow:
        row = self._console.get_workspace(workspace_id)

        if row is None:
            raise WorkspaceNotFoundError(workspace_id)

        return row

    def _record(
        self,
        actor: StaffActor,
        action: AdminAction,
        row: WorkspaceRow,
        meta: dict[str, object],
    ) -> None:
        self._admin_audit.did(
            actor.logged,
            action,
            workspace_id=row.workspace.id,
            workspace_slug=row.workspace.slug,
            meta=dict(meta),
        )
        self._session.commit()


def get_admin_billing_service(
    session: SessionDep,
    console: AdminConsoleRepositoryDep,
    subscriptions: SubscriptionRepositoryDep,
    overrides: PlanOverrideRepositoryDep,
    billing: SubscriptionServiceDep,
    admin_audit: AdminAuditServiceDep,
) -> AdminBillingService:
    return AdminBillingService(
        session=session,
        console=console,
        subscriptions=subscriptions,
        overrides=overrides,
        billing=billing,
        admin_audit=admin_audit,
    )


AdminBillingServiceDep = Annotated[
    AdminBillingService,
    Depends(get_admin_billing_service),
]
