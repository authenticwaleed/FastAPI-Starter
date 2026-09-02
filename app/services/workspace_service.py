import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    InsufficientWorkspaceRoleError,
    SlugAlreadyExistsError,
    StaffCannotActAsTenantError,
    WorkspaceLifecycleError,
    WorkspaceNotFoundError,
    WorkspaceSuspendedError,
)
from app.db.session import SessionDep
from app.models.audit_log import AuditEvent
from app.models.staff_member import StaffMember
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate
from app.services.audit_service import AuditService, AuditServiceDep

# Who may change the workspace itself, and who may close it. Named here
# rather than written into each method, so the answer to "what does an
# admin get?" is one place to read and one place to change.
MAY_ADMINISTER = frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})
MAY_CLOSE = frozenset({WorkspaceRole.OWNER})

# Everyone whose job involves customers. An agent handles the people
# messaging the business, so adding and correcting a contact is the work
# rather than an administrative act. A viewer reads and nothing else.
MAY_HANDLE_CUSTOMERS = frozenset(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.AGENT}
)


@dataclass(frozen=True)
class WorkspaceAccess:
    """A workspace, and whatever it was that permitted reaching it.

    Nothing hands out a Workspace on its own. Carrying the proof with it
    means every later decision -- may this person rename it, close it,
    read its contacts -- is answered from something already established,
    rather than from a second lookup somebody could forget to do.

    Two kinds of proof, and exactly one of them per instance.

    A **membership** is the ordinary case: somebody on the customer's own
    team, with a role that says what they may do.

    A **staff actor** is a platform support engineer holding a live,
    time-boxed grant. They have no membership, and giving them one --
    even a fabricated one that never reaches the database -- was the
    tempting mistake this shape exists to refuse. It would put them in
    the customer's member list, in their seat count, and in their audit
    log as an ordinary colleague, which is the one property this feature
    must never have.
    """

    workspace: Workspace
    membership: WorkspaceMembership | None = None
    staff_actor: StaffMember | None = None

    def __post_init__(self) -> None:
        """Exactly one proof, checked where it cannot be skipped.

        Neither would be a workspace nobody proved they could reach.
        Both would be a staff member wearing a customer's role, which is
        the thing the whole arrangement is arranged against -- and it is
        worth being unable to construct rather than merely discouraged.
        """
        if (self.membership is None) == (self.staff_actor is None):
            raise ValueError(
                "workspace access needs a membership or a staff actor, not both"
            )

    @property
    def role(self) -> WorkspaceRole:
        """What the holder may do inside this workspace.

        A staff actor reads, whatever their rank on the platform: a
        support grant is permission to look at a customer's account, not
        permission to act as the customer. `VIEWER` is exactly that --
        "reads and nothing else" -- so every role check already written
        refuses them, and none of those checks had to learn that staff
        exist.

        Not the whole guard on its own, and it is worth saying so here.
        Several services take their role check from the route rather than
        repeating it, so this stops a staff actor at every tenant route
        and at every service that checks; `actor_user_id` below is what
        stops one that does neither.
        """
        if self.membership is None:
            return WorkspaceRole.VIEWER

        return self.membership.role

    @property
    def actor_user_id(self) -> int:
        """Whose id belongs on this workspace's own audit entry.

        Raises for a staff actor rather than answering, and the raise is
        the point rather than an inconvenience. An entry in a customer's
        log naming a support engineer among their own people is precisely
        what this design exists to prevent, and returning their id -- or
        a bare `None`, which reads as "a payment provider did it" -- would
        write exactly that.

        Unreachable in practice: a staff actor is a viewer, and every
        path that records something first requires a role a viewer does
        not have. This is where it stops if one ever does not, rather
        than where it quietly lies.
        """
        if self.membership is None:
            raise StaffCannotActAsTenantError(self.workspace.id)

        return self.membership.user_id


class WorkspaceService:
    """The tenant boundary. Owns the transaction, not the queries."""

    def __init__(
        self,
        session: Session,
        workspaces: WorkspaceRepository,
        memberships: WorkspaceMembershipRepository,
        audit: AuditService,
    ) -> None:
        self._session = session
        self._workspaces = workspaces
        self._memberships = memberships
        self._audit = audit

    def create(self, payload: WorkspaceCreate, *, creator: User) -> Workspace:
        """Create a workspace and make its creator the owner.

        The two are one transaction on purpose. A workspace with no owner
        is a business nobody can administer, and it should not be possible
        for a crash between two commits to produce one.
        """
        if self._workspaces.get_by_slug(payload.slug) is not None:
            raise SlugAlreadyExistsError(payload.slug)

        try:
            workspace = self._workspaces.create(
                name=payload.name,
                slug=payload.slug,
                timezone=payload.timezone,
                default_currency=payload.default_currency,
                created_by_user_id=creator.id,
            )
            self._memberships.create(
                workspace_id=workspace.id,
                user_id=creator.id,
                role=WorkspaceRole.OWNER,
            )
            # The first line of the workspace's own history, written in
            # the transaction that created it -- so there is no workspace
            # anywhere whose audit log does not begin with its creation.
            self._audit.did(
                workspace.id,
                AuditEvent.WORKSPACE_CREATED,
                actor_user_id=creator.id,
                meta={"name": workspace.name, "slug": workspace.slug},
            )
            self._session.commit()
        except IntegrityError as exc:
            # Two requests can both pass the check above; the unique index
            # on the slug is what actually settles which one wins.
            self._session.rollback()
            raise SlugAlreadyExistsError(payload.slug) from exc

        return workspace

    def list_for(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[Workspace], int]:
        workspaces = self._workspaces.list_for_user(
            user.id,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

        return workspaces, self._workspaces.count_for_user(user.id)

    def access(self, workspace_id: uuid.UUID, user: User) -> WorkspaceAccess:
        """Resolve a workspace id into a workspace this user may reach.

        Every one of the three refusals raises the same error. A stranger
        must not be able to tell "no such workspace" from "one exists and
        you are not in it": the difference is exactly what turns the id in
        a URL into a way of discovering which businesses have accounts.
        """
        workspace = self._workspaces.get(workspace_id)

        if workspace is None or workspace.status == WorkspaceStatus.CANCELLED:
            raise WorkspaceNotFoundError(workspace_id)

        membership = self._memberships.get_for_user(workspace_id, user.id)

        if membership is None or membership.status != MembershipStatus.ACTIVE:
            raise WorkspaceNotFoundError(workspace_id)

        return WorkspaceAccess(workspace=workspace, membership=membership)

    def update(self, access: WorkspaceAccess, payload: WorkspaceUpdate) -> Workspace:
        _require(access, MAY_ADMINISTER)

        # Read before the update, because "was" is the half of a change
        # that cannot be recovered afterwards. Only the fields actually
        # supplied: a PATCH that renamed a workspace should not leave an
        # entry claiming its timezone was set to the value it already had.
        changed = {
            field: {"from": getattr(access.workspace, field), "to": value}
            for field, value in (
                ("name", payload.name),
                ("timezone", payload.timezone),
                ("default_currency", payload.default_currency),
            )
            if value is not None and value != getattr(access.workspace, field)
        }

        self._workspaces.update(
            access.workspace,
            name=payload.name,
            timezone=payload.timezone,
            default_currency=payload.default_currency,
        )

        if changed:
            # Nothing recorded for a PATCH that changed nothing. An audit
            # log full of entries saying somebody saved a form without
            # editing it is one nobody reads.
            self._audit.did(
                access.workspace.id,
                AuditEvent.WORKSPACE_UPDATED,
                actor_user_id=access.actor_user_id,
                meta={"changed": changed},
            )

        self._session.commit()

        return access.workspace

    def cancel(self, access: WorkspaceAccess) -> Workspace:
        """Close a workspace, and start the clock on its data.

        Two things, and the second is what Phase 30 asks for. The row is
        marked `cancelled`, which takes it out of every listing and makes
        every path to it answer 404; and `erase_after` is set, which is
        the date its records are destroyed.

        Not destroyed now, deliberately. A deletion workflow has to do two
        things that pull against each other -- actually delete, and not be
        instant -- and a grace period is how both are true: somebody who
        closes the wrong account on a Friday can say so on Monday, and a
        customer who asks when their data goes gets a date rather than a
        promise.

        The date is recorded in the audit log as well as on the row,
        because the log outlives the workspace and is the only thing that
        will still say the erasure was asked for.
        """
        _require(access, MAY_CLOSE)

        return self._close(access.workspace, actor_user_id=access.actor_user_id)

    def _close(
        self,
        workspace: Workspace,
        *,
        actor_user_id: int | None = None,
        by_staff: str | None = None,
    ) -> Workspace:
        """Mark it closed and set the date, whoever asked.

        One body for both doors. The platform can close an account on a
        customer's behalf -- for non-payment, for abuse, at their request
        over the phone -- and if that took a different path the two would
        eventually schedule erasure differently, which means a business
        whose data goes on a day nobody told them about.
        """
        erase_after = datetime.now(UTC) + timedelta(
            days=get_settings().erasure_grace_days
        )

        self._workspaces.set_status(
            workspace,
            WorkspaceStatus.CANCELLED,
            erase_after=erase_after,
        )
        self._audit.did(
            workspace.id,
            AuditEvent.WORKSPACE_CLOSED,
            actor_user_id=actor_user_id,
            by_staff=by_staff,
            meta={"erase_after": erase_after.isoformat()},
        )
        self._session.commit()

        return workspace

    # --- what the platform may do to a workspace --------------------------
    #
    # These take a Workspace and the address of the staff member behind
    # the act rather than a WorkspaceAccess, because there is no access
    # to have: a support engineer holds no membership, and a fabricated
    # one is the thing this codebase refuses. The role check for them is
    # on the admin route, and the service they end up in is this one --
    # so a workspace closed by staff schedules its erasure exactly the
    # way a customer closing their own account does.

    def suspend(self, workspace: Workspace, *, by_staff: str, reason: str) -> Workspace:
        """Freeze an account: reachable, readable, and unchangeable.

        Refused if it is already suspended rather than quietly replacing
        the reason, because the reason and the state were recorded
        together and a second one would describe a freeze that was
        already in force.
        """
        if workspace.status == WorkspaceStatus.SUSPENDED:
            raise WorkspaceLifecycleError(workspace.id, "already suspended")

        if workspace.status == WorkspaceStatus.CANCELLED:
            raise WorkspaceLifecycleError(
                workspace.id, "closed accounts cannot be suspended"
            )

        self._workspaces.set_status(workspace, WorkspaceStatus.SUSPENDED)
        self._audit.did(
            workspace.id,
            AuditEvent.WORKSPACE_SUSPENDED,
            by_staff=by_staff,
            meta={"reason": reason},
        )
        self._session.commit()

        return workspace

    def unsuspend(self, workspace: Workspace, *, by_staff: str) -> Workspace:
        """Thaw an account.

        A no-op on one that is not frozen, and nothing is recorded for
        it. Un-suspending something that was never suspended is the
        safest request on this surface, and refusing it would be a
        confusing answer to somebody who is trying to put things right.
        """
        if workspace.status != WorkspaceStatus.SUSPENDED:
            return workspace

        self._workspaces.set_status(workspace, WorkspaceStatus.ACTIVE)
        self._audit.did(
            workspace.id,
            AuditEvent.WORKSPACE_UNSUSPENDED,
            by_staff=by_staff,
        )
        self._session.commit()

        return workspace

    def close_for_staff(self, workspace: Workspace, *, by_staff: str) -> Workspace:
        """Close an account on the customer's behalf.

        The same path a customer's own close takes, deliberately: same
        status, same grace period, same erasure job. A second closing
        route that set the date differently is how a business ends up
        erased on a day nobody told them about.
        """
        if workspace.status == WorkspaceStatus.CANCELLED:
            raise WorkspaceLifecycleError(workspace.id, "already closed")

        return self._close(workspace, by_staff=by_staff)

    def restore(self, workspace: Workspace, *, by_staff: str) -> Workspace:
        """Bring a closed account back, if its date has not passed.

        Refused after `erase_after` rather than pretending. Once the date
        is behind us the erasure job may have run, may be running, or may
        run in the next minute -- and answering "restored" to any of
        those would be a promise this cannot keep.
        """
        if workspace.status != WorkspaceStatus.CANCELLED:
            raise WorkspaceLifecycleError(workspace.id, "this account is not closed")

        if workspace.erase_after is not None and workspace.erase_after <= datetime.now(
            UTC
        ):
            raise WorkspaceLifecycleError(
                workspace.id,
                "its erasure date has passed and its data may already be gone",
            )

        self._workspaces.set_status(workspace, WorkspaceStatus.ACTIVE)
        # Cleared, so the sweep stops finding it. A restored workspace
        # with a date still on it is one that gets erased anyway.
        self._workspaces.clear_erasure(workspace)
        self._audit.did(
            workspace.id,
            AuditEvent.WORKSPACE_RESTORED,
            by_staff=by_staff,
        )
        self._session.commit()

        return workspace

    def reschedule_erasure(
        self,
        workspace: Workspace,
        *,
        by_staff: str,
        erase_after: datetime,
    ) -> Workspace:
        """Move the date a closed account's records are destroyed.

        Both directions. Bringing it forward is what a customer asking to
        be forgotten sooner looks like; pushing it out is what a dispute
        or a legal hold looks like, and having neither would mean doing
        one of them in a database console.
        """
        if workspace.status != WorkspaceStatus.CANCELLED:
            raise WorkspaceLifecycleError(
                workspace.id,
                "only a closed account has an erasure date",
            )

        was = workspace.erase_after

        self._workspaces.set_status(
            workspace,
            WorkspaceStatus.CANCELLED,
            erase_after=erase_after,
        )
        self._audit.did(
            workspace.id,
            AuditEvent.WORKSPACE_CLOSED,
            by_staff=by_staff,
            meta={
                "from": was.isoformat() if was else None,
                "to": erase_after.isoformat(),
            },
        )
        self._session.commit()

        return workspace

    def erase_now(self, workspace: Workspace) -> None:
        """Destroy a workspace and everything it holds, immediately.

        The most destructive call in the product, and the least
        ceremonious code in this file -- everything that makes it safe
        happens before it: an owner's rank, the slug typed back, and an
        audit entry written and committed *before* this runs rather than
        after, because after there is no workspace to write about.

        Nothing is recorded in the customer's own log here. There is
        nowhere to put it: the entry would belong to the workspace being
        deleted and would go with it, which is the reason
        `admin_audit_logs` exists and does not cascade.
        """
        self._workspaces.erase(workspace)
        self._session.commit()

    def sole_owned_workspace_ids(self, user: User) -> list[uuid.UUID]:
        return self._memberships.sole_owned_workspace_ids(user.id)


def require_writable(access: WorkspaceAccess) -> None:
    """Refuse if this workspace is frozen.

    `SUSPENDED` was a word before this: the enum declared it, nothing set
    it, and nothing checked it, so a workspace marked suspended kept
    working normally. This is the half that makes it mean something.

    Reachable and frozen, rather than locked out. That is the useful
    reading of a suspension and the one the enum's own comment promises:
    a business that has not paid should be able to read its history,
    export what it needs and settle the bill. Taking their records away
    over an invoice punishes them for the thing you want them to fix.

    Called from the dependency every workspace-scoped route resolves,
    against the request's method, so one check covers every write on the
    tenant surface rather than one per service. Anything reaching a
    service by another road -- a job, a webhook -- decides for itself,
    and the assistant's reply path is the one that does.
    """
    if access.workspace.status == WorkspaceStatus.SUSPENDED:
        raise WorkspaceSuspendedError(access.workspace.id)


def _require(access: WorkspaceAccess, allowed: frozenset[WorkspaceRole]) -> None:
    if access.role not in allowed:
        raise InsufficientWorkspaceRoleError(access.workspace.id, access.role)


def get_workspace_repository(session: SessionDep) -> WorkspaceRepository:
    return WorkspaceRepository(session)


WorkspaceRepositoryDep = Annotated[
    WorkspaceRepository,
    Depends(get_workspace_repository),
]


def get_workspace_membership_repository(
    session: SessionDep,
) -> WorkspaceMembershipRepository:
    return WorkspaceMembershipRepository(session)


WorkspaceMembershipRepositoryDep = Annotated[
    WorkspaceMembershipRepository,
    Depends(get_workspace_membership_repository),
]


def get_workspace_service(
    session: SessionDep,
    workspaces: WorkspaceRepositoryDep,
    memberships: WorkspaceMembershipRepositoryDep,
    audit: AuditServiceDep,
) -> WorkspaceService:
    return WorkspaceService(
        session=session,
        workspaces=workspaces,
        memberships=memberships,
        audit=audit,
    )


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
