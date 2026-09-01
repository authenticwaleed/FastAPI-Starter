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
    WorkspaceNotFoundError,
)
from app.db.session import SessionDep
from app.models.audit_log import AuditEvent
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
    """A workspace together with the membership that permitted reaching it.

    Nothing hands out a Workspace on its own. Carrying the membership with
    it means every later decision -- may this person rename it, close it,
    read its contacts -- is answered from a role that was already proved,
    rather than from a second lookup somebody could forget to do.
    """

    workspace: Workspace
    membership: WorkspaceMembership

    @property
    def role(self) -> WorkspaceRole:
        return self.membership.role


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
                actor_user_id=access.membership.user_id,
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

        erase_after = datetime.now(UTC) + timedelta(
            days=get_settings().erasure_grace_days
        )

        self._workspaces.set_status(
            access.workspace,
            WorkspaceStatus.CANCELLED,
            erase_after=erase_after,
        )
        self._audit.did(
            access.workspace.id,
            AuditEvent.WORKSPACE_CLOSED,
            actor_user_id=access.membership.user_id,
            meta={"erase_after": erase_after.isoformat()},
        )
        self._session.commit()

        return access.workspace

    def sole_owned_workspace_ids(self, user: User) -> list[uuid.UUID]:
        return self._memberships.sole_owned_workspace_ids(user.id)


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
