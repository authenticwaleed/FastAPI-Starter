from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.models.ecommerce_account import EcommerceAccountStatus
from app.models.subscription import BillingProviderName, SubscriptionStatus
from app.models.whatsapp_account import (
    MessagingProviderName,
    WhatsAppAccountStatus,
)
from app.models.workspace import WorkspaceStatus
from app.models.workspace_membership import MembershipStatus, WorkspaceRole
from app.services.plans import PlanTier

# --- workspaces -------------------------------------------------------------


class AdminWorkspaceSummary(BaseModel):
    """One line of the console's search results.

    The owner's address is here because a list of workspace names is not
    something support can act on -- the ticket says who wrote in, not
    what their business is called. Null where the owner has closed their
    account, which is a real state and one somebody would be searching
    about.

    `erase_after` is on the summary and not only the detail. A closed
    workspace with a date three days away is the row that has to stand
    out from a list, because after that date there is nothing to restore.
    """

    id: UUID
    name: str
    slug: str
    status: WorkspaceStatus
    plan: PlanTier
    owner_email: EmailStr | None
    erase_after: datetime | None
    created_at: datetime


class AdminWorkspacePage(BaseModel):
    items: list[AdminWorkspaceSummary]
    total: int
    page: int
    page_size: int


class AdminWorkspaceCounts(BaseModel):
    """How much of everything a workspace holds.

    Counts, and this is the line the phase stops at. "Eleven thousand
    messages and nothing since March" answers most support questions
    without anybody reading a message -- and reading one needs Phase A3,
    which is granted for a reason and visible to the customer.
    """

    members: int
    contacts: int
    conversations: int
    messages: int
    knowledge_documents: int


class AdminWorkspaceDetail(AdminWorkspaceSummary):
    """One workspace, in as much detail as metadata allows."""

    timezone: str
    default_currency: str
    counts: AdminWorkspaceCounts
    updated_at: datetime


class AdminMember(BaseModel):
    """One person on a customer's team, as staff see them.

    The same fields the customer's own member list shows. Deliberately
    the same: what support quotes back to a business should be what that
    business can see for itself, and a second shape would eventually be a
    second answer.
    """

    user_id: int
    name: str
    email: EmailStr
    role: WorkspaceRole
    status: MembershipStatus
    joined_at: datetime


class AdminSubscription(BaseModel):
    """What the payment provider says about this workspace.

    The provider's identifiers are here on purpose: they are how somebody
    finds the same subscription in the provider's dashboard, which is
    where refunds and invoice corrections belong -- this surface reads
    billing, it does not move money.

    They are also not secrets. A customer id is a handle, useless without
    the API key that this application keeps and never returns.
    """

    id: UUID
    provider: BillingProviderName
    provider_customer_id: str | None
    provider_subscription_id: str | None
    plan: PlanTier
    status: SubscriptionStatus
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    created_at: datetime
    updated_at: datetime


class AdminBilling(BaseModel):
    """What the provider says, and what the workspace actually gets.

    Two fields because they answer different questions, and the gap
    between them is where billing support happens. A `past_due`
    subscription still entitles a business to its plan while the provider
    retries, so a screen showing only the status would have somebody
    telling a customer their account is restricted when it is not.

    `subscription` is null for a workspace that has never paid, which is
    not the same as one whose payment failed. `plan` is what applies in
    both cases.
    """

    plan: PlanTier
    subscription: AdminSubscription | None


class AdminWhatsApp(BaseModel):
    """A connected number, without the credential behind it.

    There is no field here for the access token and there will not be
    one. It is encrypted at rest, this surface never decrypts it, and the
    support question is whether the number is connected and working --
    never what the token is.
    """

    provider: MessagingProviderName
    phone_number: str
    # The provider's handle for the number, which is what a Meta support
    # ticket is opened with. A public identifier, not a credential.
    external_phone_number_id: str
    status: WhatsAppAccountStatus
    connected_at: datetime


class AdminStorefront(BaseModel):
    """A connected shop, without the credential behind it.

    Same rule as the number above: the domain and when it last synced are
    the support questions. "Connected in March and last synced in April"
    is what a stale catalogue looks like from here.
    """

    provider: str
    shop_domain: str
    status: EcommerceAccountStatus
    last_synced_at: datetime | None
    created_at: datetime


class AdminIntegrations(BaseModel):
    """What a business has connected, each null where it has not.

    Null rather than an absent key, so a console can render "not
    connected" without having to know which integrations exist.
    """

    whatsapp: AdminWhatsApp | None
    storefront: AdminStorefront | None


# --- people -----------------------------------------------------------------


class AdminUserSummary(BaseModel):
    """One account, as a search result.

    No password hash, and no field that could ever hold one. The same
    rule the customer-facing user schema follows, and for a stronger
    reason here: this response is about somebody who is not the person
    reading it.
    """

    id: int
    name: str
    email: EmailStr
    is_active: bool
    email_verified_at: datetime | None
    created_at: datetime


class AdminUserPage(BaseModel):
    items: list[AdminUserSummary]
    total: int
    page: int
    page_size: int


class AdminUserMembership(BaseModel):
    """One workspace an account belongs to, or used to.

    Removed memberships and cancelled workspaces are both included, which
    the customer's own view of themselves would not show. "They were an
    admin of that business until it closed" is the answer to a support
    question rather than noise.
    """

    workspace_id: UUID
    name: str
    slug: str
    workspace_status: WorkspaceStatus
    role: WorkspaceRole
    status: MembershipStatus
    joined_at: datetime


class AdminUserSession(BaseModel):
    """One live sign-in, as staff see it.

    The same fields the account's owner sees in their own session list,
    and no token: what is stored is a digest of the refresh secret, and
    nothing anywhere returns it.
    """

    id: UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_address: str | None


class AdminUserDetail(AdminUserSummary):
    """One account, with where it belongs and where it is signed in.

    Both lists are empty for somebody who registered and never went any
    further, which is a common state rather than an error -- and the
    reason this answers cleanly instead of refusing.
    """

    memberships: list[AdminUserMembership]
    sessions: list[AdminUserSession]
