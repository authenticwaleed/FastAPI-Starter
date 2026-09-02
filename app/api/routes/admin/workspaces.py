import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.staff import StaffDep
from app.api.errors import (
    ADMIN_FORBIDDEN,
    ADMIN_NOT_FOUND,
    ADMIN_UNAUTHORISED,
    RATE_LIMITED,
)
from app.api.routes.audit import entry_of
from app.models.audit_log import AuditEvent
from app.models.ecommerce_account import EcommerceAccount
from app.models.subscription import Subscription
from app.models.user import User
from app.models.whatsapp_account import WhatsAppAccount
from app.models.workspace import WorkspaceStatus
from app.models.workspace_membership import WorkspaceMembership
from app.repositories.admin_console_repository import (
    WorkspaceCounts,
    WorkspaceRow,
)
from app.schemas.admin_console import (
    AdminBilling,
    AdminIntegrations,
    AdminMember,
    AdminStorefront,
    AdminSubscription,
    AdminWhatsApp,
    AdminWorkspaceCounts,
    AdminWorkspaceDetail,
    AdminWorkspacePage,
    AdminWorkspaceSummary,
)
from app.schemas.audit import AuditPage
from app.schemas.usage import MetricUsage, UsageSummary
from app.services.admin_workspace_service import AdminWorkspaceServiceDep
from app.services.plans import PlanTier
from app.services.usage_service import Usage

router = APIRouter(prefix="/workspaces", tags=["platform"])

PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}
FOUND = {**PLATFORM, **ADMIN_NOT_FOUND}


# Any staff member, at any rank, for every route in this file. Reading the
# console is what `support` is *for* -- it is the rank that answers
# tickets -- and there is nothing here that changes anything, so a higher
# bar would only mean support asking an admin to look at a screen for
# them. What needs a rank is Phase A3, where reading stops being
# aggregates and starts being a customer's own messages.
@router.get("", responses=PLATFORM)
def search_workspaces(
    actor: StaffDep,
    service: AdminWorkspaceServiceDep,
    q: Annotated[str | None, Query(max_length=320)] = None,
    status: Annotated[WorkspaceStatus | None, Query()] = None,
    plan: Annotated[PlanTier | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminWorkspacePage:
    """Find a business by name, by slug, or by the address of anyone in it.

    The third is the one a ticket actually arrives with. The plan asks
    for the owner's address; matching any active member is a superset of
    that and the same thing in practice, because whoever writes in is
    whoever noticed the problem and is as often an agent as the owner.

    `status` and `plan` narrow rather than search. Cancelled workspaces
    are included by default and carry their `erase_after` date -- unlike
    the customer's own API, which pretends a closed workspace is gone.
    """
    found, total = service.search(
        actor,
        term=q,
        status=status,
        plan=plan,
        page=page,
        page_size=page_size,
    )

    return AdminWorkspacePage(
        items=[summary_of(row) for row in found],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{workspace_id}", responses=FOUND)
def read_workspace(
    workspace_id: uuid.UUID,
    actor: StaffDep,
    service: AdminWorkspaceServiceDep,
) -> AdminWorkspaceDetail:
    """One workspace, with how much of everything it holds.

    A 404 here means the workspace does not exist, and nothing else. A
    cancelled one is found, with the date its records are due to be
    destroyed, because "it was closed last week and goes on the 30th" is
    the answer to the ticket.
    """
    row, counts = service.read(actor, workspace_id)

    return _detail(row, counts)


@router.get("/{workspace_id}/members", responses=FOUND)
def read_workspace_members(
    workspace_id: uuid.UUID,
    actor: StaffDep,
    service: AdminWorkspaceServiceDep,
) -> list[AdminMember]:
    """Who is on the team, and with what role.

    Unpaginated, like the customer's own member list: a workspace's team
    is people, and the plans this is built for cap that in the low tens.
    """
    return [
        _member(membership, user)
        for membership, user in service.members(actor, workspace_id)
    ]


@router.get("/{workspace_id}/subscription", responses=FOUND)
def read_workspace_subscription(
    workspace_id: uuid.UUID,
    actor: StaffDep,
    service: AdminWorkspaceServiceDep,
) -> AdminBilling:
    """What the provider says, and what the workspace actually gets.

    Both. A `past_due` subscription still entitles a business to its plan
    while the provider retries, so an answer carrying only the status
    would have somebody telling a customer their account is restricted
    when it is not.

    Reading only. Refunds and invoice corrections stay in the provider's
    dashboard, which is better at them and is already the system of
    record -- the provider ids in this response are how somebody gets
    there.
    """
    subscription, plan = service.subscription(actor, workspace_id)

    return AdminBilling(
        plan=plan,
        subscription=_subscription(subscription) if subscription else None,
    )


@router.get("/{workspace_id}/usage", responses=FOUND)
def read_workspace_usage(
    workspace_id: uuid.UUID,
    actor: StaffDep,
    service: AdminWorkspaceServiceDep,
) -> UsageSummary:
    """What this workspace has used, over the period it is billed for.

    The same shape the customer's own usage page returns, from the same
    meter. A support engineer and a customer looking at "how many AI
    replies this month" should not be able to see two different numbers.
    """
    return _usage(service.usage(actor, workspace_id))


@router.get("/{workspace_id}/integrations", responses=FOUND)
def read_workspace_integrations(
    workspace_id: uuid.UUID,
    actor: StaffDep,
    service: AdminWorkspaceServiceDep,
) -> AdminIntegrations:
    """WhatsApp and the storefront: connected or not, and how healthily.

    No credential of any kind. Both rows carry a provider token
    encrypted at rest, and nothing on this surface decrypts one for any
    reason -- the response models have nowhere to put it.
    """
    whatsapp, storefront = service.integrations(actor, workspace_id)

    return AdminIntegrations(
        whatsapp=_whatsapp(whatsapp) if whatsapp else None,
        storefront=_storefront(storefront) if storefront else None,
    )


@router.get("/{workspace_id}/audit", responses=FOUND)
def read_workspace_audit(
    workspace_id: uuid.UUID,
    actor: StaffDep,
    service: AdminWorkspaceServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    event: Annotated[AuditEvent | None, Query()] = None,
    actor_user_id: Annotated[int | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> AuditPage:
    """The business's own record of what its people did to it.

    Their log, and reading it is recorded in ours. That pairing is the
    arrangement this whole surface rests on: a customer can see what
    their colleagues did, and the platform can see who went looking
    through it.

    No plan is required, unlike the customer's own route. Audit logs are
    a paid feature for a business; whether support can answer a ticket
    about one is not a decision that business's plan gets to make.
    """
    entries, total = service.audit(
        actor,
        workspace_id,
        page=page,
        page_size=page_size,
        event=event,
        actor_user_id=actor_user_id,
        since=since,
        until=until,
    )

    return AuditPage(
        items=[entry_of(entry, user) for entry, user in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


def summary_of(row: WorkspaceRow) -> AdminWorkspaceSummary:
    """One workspace as the console shows it in a list.

    Public, and shared with the lifecycle routes, so that what suspending
    an account answers with is exactly what the search result beside it
    would say -- the resolved plan included, which is an expression
    rather than a column on the workspace.
    """
    return AdminWorkspaceSummary(
        id=row.workspace.id,
        name=row.workspace.name,
        slug=row.workspace.slug,
        status=row.workspace.status,
        plan=row.plan,
        owner_email=row.owner_email,
        erase_after=row.workspace.erase_after,
        created_at=row.workspace.created_at,
    )


def _detail(row: WorkspaceRow, counts: WorkspaceCounts) -> AdminWorkspaceDetail:
    return AdminWorkspaceDetail(
        **summary_of(row).model_dump(),
        timezone=row.workspace.timezone,
        default_currency=row.workspace.default_currency,
        counts=AdminWorkspaceCounts(
            members=counts.members,
            contacts=counts.contacts,
            conversations=counts.conversations,
            messages=counts.messages,
            knowledge_documents=counts.knowledge_documents,
        ),
        updated_at=row.workspace.updated_at,
    )


def _member(membership: WorkspaceMembership, user: User) -> AdminMember:
    return AdminMember(
        user_id=user.id,
        name=user.name,
        email=user.email,
        role=membership.role,
        status=membership.status,
        joined_at=membership.created_at,
    )


def _subscription(subscription: Subscription) -> AdminSubscription:
    return AdminSubscription(
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
    )


def _usage(measured: Usage) -> UsageSummary:
    return UsageSummary(
        period_start=measured.period.start,
        period_end=measured.period.end,
        metrics=[
            MetricUsage(
                metric=measurement.metric,
                quantity=measurement.quantity,
                limit=measurement.limit,
            )
            for measurement in measured.measurements
        ],
    )


def _whatsapp(account: WhatsAppAccount) -> AdminWhatsApp:
    """Everything except the token, and there is nowhere to put the token."""
    return AdminWhatsApp(
        provider=account.provider,
        phone_number=account.phone_number,
        external_phone_number_id=account.external_phone_number_id,
        status=account.status,
        connected_at=account.connected_at,
    )


def _storefront(account: EcommerceAccount) -> AdminStorefront:
    return AdminStorefront(
        provider=account.provider,
        shop_domain=account.shop_domain,
        status=account.status,
        last_synced_at=account.last_synced_at,
        created_at=account.created_at,
    )
