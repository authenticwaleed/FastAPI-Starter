import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, case, func, literal, select
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.knowledge import KnowledgeDocument
from app.models.message import Message
from app.models.plan_override import PlanOverride
from app.models.subscription import Subscription
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.services.plans import FREE_PLAN, PlanTier
from app.services.subscription_service import ENTITLING


@dataclass(frozen=True)
class WorkspaceRow:
    """One line of the console's search results.

    The workspace, plus the two things that make a list of them usable:
    who owns it, and what plan it is actually on. Both come from the same
    query as the row rather than from a lookup per line -- a console that
    resolved either one workspace at a time would issue two hundred
    queries to draw one page of a hundred.
    """

    workspace: Workspace
    # Null for a workspace whose owner has closed their account. That
    # happens: the membership cascades with the user, and the workspace
    # carries on without them, which is exactly the state somebody would
    # be searching for support about.
    owner_email: str | None
    plan: PlanTier


@dataclass(frozen=True)
class WorkspaceCounts:
    """How much of everything one workspace holds.

    Counts and nothing else, which is the line this phase stops at: the
    number of conversations answers "is this business actually using the
    product", and reading one of them is a different act behind a
    time-boxed grant.
    """

    members: int
    contacts: int
    conversations: int
    messages: int
    knowledge_documents: int


def entitled_plan() -> ColumnElement[str]:
    """The plan a workspace is really on, as a column.

    The same three sources in the same order as
    `SubscriptionService.plan_for` -- an override, then the subscription,
    then free -- expressed once more in SQL because a console asks about
    every workspace at once rather than one at a time.

    Two answers to one question is a risk worth naming, so as little as
    possible is restated: `ENTITLING` is imported from the service, the
    fallback is `FREE_PLAN.tier` rather than a literal, and the override
    is matched by the same "no date or a date ahead" the repository uses.
    What is left is the shape, and a test holds the two side by side on
    every combination that matters.

    Both `NULL` cases fall through correctly and neither is an accident.
    A workspace with no override has a NULL granted plan, so `coalesce`
    moves on; one with no subscription has a NULL status, which is not in
    `ENTITLING`, so it reads as free -- which is what it is.
    """
    return func.coalesce(
        _granted_plan(),
        case(
            (Subscription.status.in_(ENTITLING), Subscription.plan),
            else_=literal(FREE_PLAN.tier.value),
        ),
    )


def _granted_plan() -> ColumnElement[str | None]:
    """The plan the platform granted this workspace, if one is in force.

    A correlated subquery rather than a join, so that adding this to a
    search cannot change how many rows it returns -- the unique
    constraint makes at most one match, and a subquery says so at a
    glance where a join would need reading twice.
    """
    return (
        select(PlanOverride.plan)
        .where(
            PlanOverride.workspace_id == Workspace.id,
            (PlanOverride.expires_at.is_(None))
            | (PlanOverride.expires_at > func.now()),
        )
        .scalar_subquery()
    )


class AdminConsoleRepository:
    """The queries the read-only console runs, none of them tenant-scoped.

    Every other repository in this application narrows by workspace,
    because everything else is a customer looking at their own data. This
    one searches across all of them, which is the whole point of the
    surface and the reason it lives in a file whose name says so.

    Two rules run through all of it, and both are the plan's.

    Everything is counted with an explicit query. A console that reached
    for a relationship and let the ORM lazy-load it would issue a query
    per row, and the page nobody notices that on is the page with ten
    workspaces in a test.

    And nothing here reads a customer's content. There is no method that
    returns a conversation, a message, a contact or a document -- only how
    many there are. Reading the thing itself needs Phase A3, which is
    time-boxed and visible to the customer.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- workspaces --------------------------------------------------------

    def search_workspaces(
        self,
        *,
        term: str | None = None,
        status: WorkspaceStatus | None = None,
        plan: PlanTier | None = None,
        limit: int,
        offset: int,
    ) -> list[WorkspaceRow]:
        """A page of workspaces, newest first, with owner and plan.

        Newest first because the workspace somebody is asking about is
        far more often a recent signup than a five-year-old account, and
        because a stable secondary sort on the id keeps two workspaces
        created in the same second from swapping places between pages.
        """
        rows = self._session.execute(
            select(Workspace, _owner_email(), entitled_plan())
            .outerjoin(Subscription, Subscription.workspace_id == Workspace.id)
            .where(*self._workspace_filters(term, status, plan))
            .order_by(Workspace.created_at.desc(), Workspace.id)
            .limit(limit)
            .offset(offset)
        ).all()

        return [
            WorkspaceRow(
                workspace=workspace,
                owner_email=owner_email,
                plan=PlanTier(found),
            )
            for workspace, owner_email, found in rows
        ]

    def count_workspaces(
        self,
        *,
        term: str | None = None,
        status: WorkspaceStatus | None = None,
        plan: PlanTier | None = None,
    ) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(Workspace)
                .outerjoin(Subscription, Subscription.workspace_id == Workspace.id)
                .where(*self._workspace_filters(term, status, plan))
            )
            or 0
        )

    def get_workspace(self, workspace_id: uuid.UUID) -> WorkspaceRow | None:
        """One workspace, with the same owner and plan the list shows.

        Deliberately not `Session.get`. A detail page that resolved the
        plan differently from the list it was opened from would be a
        console people stop trusting, and the way to be sure they agree
        is for both to be this one expression.
        """
        row = self._session.execute(
            select(Workspace, _owner_email(), entitled_plan())
            .outerjoin(Subscription, Subscription.workspace_id == Workspace.id)
            .where(Workspace.id == workspace_id)
        ).first()

        if row is None:
            return None

        workspace, owner_email, plan = row

        return WorkspaceRow(
            workspace=workspace,
            owner_email=owner_email,
            plan=PlanTier(plan),
        )

    def counts(self, workspace_id: uuid.UUID) -> WorkspaceCounts:
        """Everything a workspace holds, counted in one round trip.

        Five scalar subqueries in one statement rather than five
        statements. They are all indexed on the same column and none
        depends on another, so the database can answer them together --
        and the alternative is a detail page whose cost is a multiple of
        how many things anybody thinks to add to it later.
        """
        row = self._session.execute(
            select(
                _count_where(WorkspaceMembership, workspace_id, _ACTIVE_MEMBER),
                _count_where(Contact, workspace_id),
                _count_where(Conversation, workspace_id),
                _count_where(Message, workspace_id),
                _count_where(KnowledgeDocument, workspace_id),
            )
        ).one()

        return WorkspaceCounts(
            members=row[0],
            contacts=row[1],
            conversations=row[2],
            messages=row[3],
            knowledge_documents=row[4],
        )

    def _workspace_filters(
        self,
        term: str | None,
        status: WorkspaceStatus | None,
        plan: PlanTier | None,
    ) -> list[ColumnElement[bool]]:
        """The same narrowing for the page and its total.

        Built once rather than written twice, because a count that
        filters differently from the list it counts is a pager that runs
        out of pages early -- and on this surface that reads as a
        workspace having vanished.
        """
        where: list[ColumnElement[bool]] = []

        if term:
            pattern = _contains(term)
            where.append(
                Workspace.name.ilike(pattern, escape="\\")
                | Workspace.slug.ilike(pattern, escape="\\")
                | _has_a_member_matching(pattern)
            )

        if status is not None:
            where.append(Workspace.status == status)

        if plan is not None:
            where.append(entitled_plan() == plan.value)

        return where

    # --- people ------------------------------------------------------------

    def search_users(
        self,
        *,
        term: str | None = None,
        limit: int,
        offset: int,
    ) -> Sequence[User]:
        """A page of accounts, newest first.

        By address or by name, because a support ticket arrives with one
        of the two and rarely with an id.
        """
        return self._session.scalars(
            select(User)
            .where(*self._user_filters(term))
            .order_by(User.created_at.desc(), User.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_users(self, *, term: str | None = None) -> int:
        return (
            self._session.scalar(
                select(func.count()).select_from(User).where(*self._user_filters(term))
            )
            or 0
        )

    def get_user(self, user_id: int) -> User | None:
        return self._session.get(User, user_id)

    def memberships_for_user(
        self,
        user_id: int,
    ) -> list[tuple[WorkspaceMembership, Workspace]]:
        """Every workspace this account belongs to, and in what capacity.

        Removed memberships included, because "they used to be an admin
        of that business" is the answer to a support question rather than
        noise. Cancelled workspaces too: on this surface a closed account
        is visible, unlike on the tenant one where it is deliberately
        indistinguishable from one that never existed.

        One join rather than a lookup per row, for the reason everything
        else here is one query.
        """
        rows = self._session.execute(
            select(WorkspaceMembership, Workspace)
            .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
            .where(WorkspaceMembership.user_id == user_id)
            .order_by(Workspace.created_at.desc(), Workspace.id)
        ).all()

        return [(membership, workspace) for membership, workspace in rows]

    def _user_filters(self, term: str | None) -> list[ColumnElement[bool]]:
        """The same narrowing for the page and its total.

        By address or by name, either matching anywhere in the value: a
        support ticket arrives with a fragment of one of the two -- half
        a company address, a first name -- and rarely with either in
        full.
        """
        if not term:
            return []

        pattern = _contains(term)

        return [
            User.email.ilike(pattern, escape="\\")
            | User.name.ilike(pattern, escape="\\")
        ]


# One membership per workspace per person, so "how many people are in
# this" is the count of the active ones. A removed row is history.
_ACTIVE_MEMBER = WorkspaceMembership.status == MembershipStatus.ACTIVE


def _owner_email() -> ColumnElement[str | None]:
    """The address of whoever owns this workspace, as a column.

    A correlated subquery rather than a join, and the difference matters:
    a workspace can have two owners, and a join would return it twice --
    once per owner -- quietly doubling a page of search results.

    Ordered by user id and limited to one, so the answer is stable
    between requests rather than whichever row the database reached
    first.
    """
    return (
        select(User.email)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == Workspace.id,
            WorkspaceMembership.role == WorkspaceRole.OWNER,
            _ACTIVE_MEMBER,
        )
        .order_by(User.id)
        .limit(1)
        .scalar_subquery()
    )


def _has_a_member_matching(pattern: str) -> ColumnElement[bool]:
    """Whether anybody in this workspace has an address like this.

    Any active member, not only the owner. The plan asks that a workspace
    be findable by its owner's address, and this is a superset of that
    for a reason support will meet on the first ticket: the person who
    writes in is whoever noticed the problem, and they are as often an
    agent as the owner.

    EXISTS rather than a join, so a workspace with three matching members
    is still one row.
    """
    return (
        select(literal(1))
        .select_from(WorkspaceMembership)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == Workspace.id,
            _ACTIVE_MEMBER,
            User.email.ilike(pattern, escape="\\"),
        )
        .exists()
    )


def _count_where(
    model: type[object],
    workspace_id: uuid.UUID,
    *extra: ColumnElement[bool],
) -> ColumnElement[int]:
    """How many rows of one table belong to this workspace.

    A scalar subquery so that several of these fit in one statement. Each
    one narrows on the indexed `workspace_id` that every tenant-owned
    table carries, which is the same column the tenant boundary is drawn
    on.
    """
    return (
        select(func.count())
        .select_from(model)
        .where(model.workspace_id == workspace_id, *extra)  # type: ignore[attr-defined]
        .scalar_subquery()
    )


def _contains(term: str) -> str:
    """A LIKE pattern matching `term` anywhere, with its wildcards defused.

    Escaped rather than passed through. A search for `50%` would
    otherwise match every workspace whose name begins "50", and an
    underscore would match any character at all -- so a support engineer
    pasting an address with an underscore in it would get a page of other
    people's businesses back.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    return f"%{escaped}%"
