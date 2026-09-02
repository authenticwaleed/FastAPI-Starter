"""Reading one customer's account, without reading their customers'.

The phase that makes support possible, and the line it stops at is the
point of it. Everything here is metadata and aggregates: how many
conversations a business has had, what plan it is on, who is on its team,
whether its WhatsApp number is connected. Nothing here returns a
conversation, a message, a contact or a document -- reading those is
Phase A3, which is time-boxed, granted for a reason, and visible to the
customer in their own audit log.

Every method writes to `admin_audit_logs`, and on this surface that
includes the reads. Looking at somebody else's account *is* the sensitive
act, so a log recording only changes would answer a question nobody
asked.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import WorkspaceNotFoundError
from app.db.session import SessionDep
from app.models.admin_audit_log import AdminAction
from app.models.audit_log import AuditEvent, AuditLog
from app.models.ecommerce_account import EcommerceAccount
from app.models.subscription import Subscription
from app.models.user import User
from app.models.whatsapp_account import WhatsAppAccount
from app.models.workspace import WorkspaceStatus
from app.models.workspace_membership import WorkspaceMembership
from app.repositories.admin_console_repository import (
    AdminConsoleRepository,
    WorkspaceCounts,
    WorkspaceRow,
)
from app.repositories.ecommerce_account_repository import EcommerceAccountRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.whatsapp_account_repository import WhatsAppAccountRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.admin_audit_service import AdminAuditService, AdminAuditServiceDep
from app.services.audit_service import AuditService, AuditServiceDep
from app.services.ecommerce_service import EcommerceAccountRepositoryDep
from app.services.plans import PLANS, PlanTier
from app.services.staff_service import StaffActor
from app.services.subscription_service import SubscriptionRepositoryDep
from app.services.usage_service import Usage, UsageService, UsageServiceDep
from app.services.whatsapp_service import WhatsAppAccountRepositoryDep
from app.services.workspace_service import WorkspaceMembershipRepositoryDep


class AdminWorkspaceService:
    """One customer's account, from the outside.

    Nine collaborators, which is more than anything else in this
    application has and is what a console is: seven of them are the
    tables a support engineer has to be able to look at, and they are the
    existing repositories rather than new queries because a second way of
    reading a subscription would eventually disagree with the first.

    Every method here follows the same three steps -- prove the workspace
    exists, read one thing, record that it was read -- and the first step
    is what makes the last one worth anything. An audit row naming a
    workspace id that never existed would be noise; every entry this
    writes names a real business, by id and by slug.
    """

    def __init__(
        self,
        session: Session,
        console: AdminConsoleRepository,
        admin_audit: AdminAuditService,
        memberships: WorkspaceMembershipRepository,
        subscriptions: SubscriptionRepository,
        usage: UsageService,
        whatsapp: WhatsAppAccountRepository,
        ecommerce: EcommerceAccountRepository,
        tenant_audit: AuditService,
    ) -> None:
        self._session = session
        self._console = console
        self._admin_audit = admin_audit
        self._memberships = memberships
        self._subscriptions = subscriptions
        self._usage = usage
        self._whatsapp = whatsapp
        self._ecommerce = ecommerce
        self._tenant_audit = tenant_audit

    # --- finding one ------------------------------------------------------

    def search(
        self,
        actor: StaffActor,
        *,
        term: str | None = None,
        status: WorkspaceStatus | None = None,
        plan: PlanTier | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[WorkspaceRow], int]:
        """The list a support engineer starts from.

        The search itself is recorded, with what was searched for. That
        is not an excess: "who went looking for this business, and when"
        is a question that only the term makes answerable, and a row
        saying somebody ran a search says nothing at all.
        """
        found = self._console.search_workspaces(
            term=term,
            status=status,
            plan=plan,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = self._console.count_workspaces(term=term, status=status, plan=plan)

        self._admin_audit.did(
            actor.logged,
            AdminAction.WORKSPACES_SEARCHED,
            meta={
                "term": term,
                "status": status.value if status else None,
                "plan": plan.value if plan else None,
                "results": total,
            },
        )
        self._session.commit()

        return found, total

    def read(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
    ) -> tuple[WorkspaceRow, WorkspaceCounts]:
        """One workspace, with how much of everything it holds.

        Counts rather than contents, which is where this phase stops.
        "Eleven thousand messages and no conversation since March" is the
        answer to most support questions, and it is not a message.
        """
        row = self._workspace(workspace_id)
        counts = self._console.counts(workspace_id)

        self._record(actor, AdminAction.WORKSPACE_READ, row)

        return row, counts

    # --- what it holds ----------------------------------------------------

    def members(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
    ) -> list[tuple[WorkspaceMembership, User]]:
        """Who is on the team, and with what role.

        The same query the customer's own member list runs, rather than a
        second one: two ways of asking who is in a workspace is two
        answers waiting to disagree, and the one support quotes back to a
        customer had better be the one the customer can see.
        """
        row = self._workspace(workspace_id)
        listed = self._memberships.list_with_users(workspace_id)

        self._record(
            actor,
            AdminAction.WORKSPACE_MEMBERS_READ,
            row,
            meta={"members": len(listed)},
        )

        return listed

    def subscription(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
    ) -> tuple[Subscription | None, PlanTier]:
        """What the provider says, and what the workspace actually gets.

        Both, because they are different questions and the gap between
        them is where billing support happens. A `past_due` subscription
        still entitles a business to its plan while the provider retries,
        so a screen showing only the status would have somebody telling a
        customer their account is restricted when it is not.

        Null for a workspace that has never paid -- which is not the same
        as one whose payment failed, and the plan says so in both cases.
        """
        row = self._workspace(workspace_id)
        subscription = self._subscriptions.get_for_workspace(workspace_id)

        self._record(
            actor,
            AdminAction.WORKSPACE_SUBSCRIPTION_READ,
            row,
            meta={"plan": row.plan.value},
        )

        return subscription, row.plan

    def usage(self, actor: StaffActor, workspace_id: uuid.UUID) -> Usage:
        """Every metric against what the plan allows, for the current period.

        Measured through the meter the customer's own usage page uses, so
        the number support quotes is the number the customer is looking
        at. The plan comes from the same expression the search results
        use, which is what stops this page and that list disagreeing
        about which plan a business is on.
        """
        row = self._workspace(workspace_id)
        measured = self._usage.summarise(workspace_id, PLANS[row.plan])

        self._record(actor, AdminAction.WORKSPACE_USAGE_READ, row)

        return measured

    def integrations(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
    ) -> tuple[WhatsAppAccount | None, EcommerceAccount | None]:
        """What this business has connected, and whether it is working.

        The rows themselves, and what the route does with them is where
        the care is: both carry an encrypted provider token, and nothing
        on this surface decrypts one for any reason. "Is the number
        connected and when was it last synced" is the support question;
        "what is the token" never is.
        """
        row = self._workspace(workspace_id)
        whatsapp = self._whatsapp.get_for_workspace(workspace_id)
        storefront = self._ecommerce.get_for_workspace(workspace_id)

        self._record(
            actor,
            AdminAction.WORKSPACE_INTEGRATIONS_READ,
            row,
            meta={
                "whatsapp": whatsapp is not None,
                "storefront": storefront is not None,
            },
        )

        return whatsapp, storefront

    def audit(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        event: AuditEvent | None = None,
        actor_user_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[tuple[AuditLog, User | None]], int]:
        """The business's own history of what its people did to it.

        Their log, not this one, and reading it is recorded in ours. That
        pairing is the whole arrangement: the customer can see what their
        colleagues did, and the platform can see who from support went
        looking through it.

        Unlike the tenant route, no plan is required. Audit logs are a
        paid feature for a customer; whether support can answer a ticket
        about a business is not something that business's plan decides.
        """
        row = self._workspace(workspace_id)
        entries, total = self._tenant_audit.list_for(
            workspace_id,
            page=page,
            page_size=page_size,
            event=event,
            actor_user_id=actor_user_id,
            since=since,
            until=until,
        )

        self._record(
            actor,
            AdminAction.WORKSPACE_AUDIT_READ,
            row,
            meta={"page": page, "page_size": page_size, "entries": total},
        )

        return entries, total

    # --- the steps they share ---------------------------------------------

    def _workspace(self, workspace_id: uuid.UUID) -> WorkspaceRow:
        """Resolve the id, honestly.

        404 only when nothing exists. The tenant boundary answers the
        same way to three different refusals, so that an id cannot be
        used to discover which businesses have accounts -- and this
        surface must not inherit that, because a support engineer who
        cannot tell "no such workspace" from "cancelled last week" cannot
        answer the ticket.

        A cancelled workspace is therefore visible here, with the date
        its data is due to be destroyed, while the customer's own API
        pretends it is gone.
        """
        row = self._console.get_workspace(workspace_id)

        if row is None:
            raise WorkspaceNotFoundError(workspace_id)

        return row

    def _record(
        self,
        actor: StaffActor,
        action: AdminAction,
        row: WorkspaceRow,
        meta: dict[str, object] | None = None,
    ) -> None:
        """Write the entry, naming the workspace twice.

        By id and by slug, because the id is nulled when the workspace is
        finally erased and the slug is what still says whose account this
        entry was about. That is the property the whole table is shaped
        around, and it is worth nothing unless every writer supplies both.
        """
        self._admin_audit.did(
            actor.logged,
            action,
            workspace_id=row.workspace.id,
            workspace_slug=row.workspace.slug,
            meta=dict(meta or {}),
        )
        self._session.commit()


def get_admin_console_repository(session: SessionDep) -> AdminConsoleRepository:
    return AdminConsoleRepository(session)


AdminConsoleRepositoryDep = Annotated[
    AdminConsoleRepository,
    Depends(get_admin_console_repository),
]


def get_admin_workspace_service(
    session: SessionDep,
    console: AdminConsoleRepositoryDep,
    admin_audit: AdminAuditServiceDep,
    memberships: WorkspaceMembershipRepositoryDep,
    subscriptions: SubscriptionRepositoryDep,
    usage: UsageServiceDep,
    whatsapp: WhatsAppAccountRepositoryDep,
    ecommerce: EcommerceAccountRepositoryDep,
    tenant_audit: AuditServiceDep,
) -> AdminWorkspaceService:
    return AdminWorkspaceService(
        session=session,
        console=console,
        admin_audit=admin_audit,
        memberships=memberships,
        subscriptions=subscriptions,
        usage=usage,
        whatsapp=whatsapp,
        ecommerce=ecommerce,
        tenant_audit=tenant_audit,
    )


AdminWorkspaceServiceDep = Annotated[
    AdminWorkspaceService,
    Depends(get_admin_workspace_service),
]
