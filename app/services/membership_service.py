from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InsufficientWorkspaceRoleError,
    LastOwnerError,
    MembershipNotFoundError,
)
from app.db.session import SessionDep
from app.models.audit_log import AuditEvent
from app.models.user import User
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceRole,
    outranks,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.audit_service import AuditService, AuditServiceDep
from app.services.workspace_service import (
    MAY_ADMINISTER,
    WorkspaceAccess,
    WorkspaceMembershipRepositoryDep,
)


def may_manage(actor: WorkspaceRole, target: WorkspaceRole) -> bool:
    """Whether someone holding `actor` may act on someone holding `target`.

    An owner may act on anyone, including another owner: somebody has to
    be able to resolve a dispute between two owners, and the last-owner
    rule already stops that leaving the workspace unadministered.

    Everyone else needs to outrank their target strictly, which is the
    plan's "owner manages admins, admin manages agents" written once. It
    also means an admin cannot demote another admin, and cannot promote
    anybody into the rank they hold themselves -- the two moves that would
    otherwise turn `admin` into `owner` in two steps.
    """
    return actor == WorkspaceRole.OWNER or outranks(actor, target)


class MembershipService:
    """Who is on a workspace's team, and who may change that.

    Every method takes the WorkspaceAccess a dependency already resolved,
    so the workspace and the caller's role in it are established facts
    before any rule here is applied. What is left to decide is the part
    that is genuinely about people: rank, and the last owner.
    """

    def __init__(
        self,
        session: Session,
        memberships: WorkspaceMembershipRepository,
        audit: AuditService,
    ) -> None:
        self._session = session
        self._memberships = memberships
        self._audit = audit

    def list_members(
        self,
        access: WorkspaceAccess,
    ) -> list[tuple[WorkspaceMembership, User]]:
        """The team. Any member may see who they work with."""
        return self._memberships.list_with_users(access.workspace.id)

    def change_role(
        self,
        access: WorkspaceAccess,
        user_id: int,
        role: WorkspaceRole,
    ) -> tuple[WorkspaceMembership, User]:
        membership, user = self._member(access, user_id)

        if not may_manage(access.role, membership.role):
            raise InsufficientWorkspaceRoleError(access.workspace.id, access.role)

        # Checked against the role being granted as well as the one being
        # taken away. Without this an admin could not demote another admin
        # but could still make an agent into one, which is the same
        # privilege handed out by a different door.
        if not may_manage(access.role, role):
            raise InsufficientWorkspaceRoleError(access.workspace.id, access.role)

        if membership.role == role:
            return membership, user

        self._refuse_to_strand(access, membership, leaving=role != WorkspaceRole.OWNER)

        was = membership.role

        self._memberships.set_role(membership, role)
        # Both roles, because this is the entry a business will actually
        # come looking for: who made whom an administrator, and what they
        # were before. "Promoted to admin" without the rank they held is
        # half an answer.
        self._audit.did(
            access.workspace.id,
            AuditEvent.MEMBER_ROLE_CHANGED,
            actor_user_id=access.actor_user_id,
            meta={"user_id": user_id, "from": was.value, "to": role.value},
        )
        self._session.commit()

        return membership, user

    def remove(self, access: WorkspaceAccess, user_id: int) -> None:
        """Take somebody off the team, or leave it yourself.

        Leaving needs no rank: anyone may walk out of a workspace they are
        in. Removing somebody else is administration, and needs both the
        role for it and a rank above theirs.

        The row is kept and marked removed rather than deleted, so that
        re-adding a former colleague restores the membership they had
        instead of colliding with it.
        """
        membership, _ = self._member(access, user_id)
        # By user rather than by membership id, which the unique
        # constraint makes the same comparison and which reads as the
        # question actually being asked.
        leaving_themselves = user_id == access.actor_user_id

        if not leaving_themselves:
            if access.role not in MAY_ADMINISTER:
                raise InsufficientWorkspaceRoleError(access.workspace.id, access.role)

            if not may_manage(access.role, membership.role):
                raise InsufficientWorkspaceRoleError(access.workspace.id, access.role)

        self._refuse_to_strand(access, membership, leaving=True)

        self._memberships.set_status(membership, MembershipStatus.REMOVED)
        # Whether they were taken off the team or walked out themselves,
        # which is the same row and two different things: the actor is the
        # same person as the subject in exactly one of those cases.
        self._audit.did(
            access.workspace.id,
            AuditEvent.MEMBER_REMOVED,
            actor_user_id=access.actor_user_id,
            meta={"user_id": user_id, "role": membership.role.value},
        )
        self._session.commit()

    def _member(
        self,
        access: WorkspaceAccess,
        user_id: int,
    ) -> tuple[WorkspaceMembership, User]:
        found = self._memberships.get_with_user(access.workspace.id, user_id)

        if found is None or found[0].status != MembershipStatus.ACTIVE:
            raise MembershipNotFoundError(access.workspace.id, user_id)

        return found

    def _refuse_to_strand(
        self,
        access: WorkspaceAccess,
        membership: WorkspaceMembership,
        *,
        leaving: bool,
    ) -> None:
        """Stop the last owner from being demoted, removed, or walking out."""
        if not leaving or membership.role != WorkspaceRole.OWNER:
            return

        if self._memberships.count_active_owners(access.workspace.id) <= 1:
            raise LastOwnerError(access.workspace.id)


def get_membership_service(
    session: SessionDep,
    memberships: WorkspaceMembershipRepositoryDep,
    audit: AuditServiceDep,
) -> MembershipService:
    return MembershipService(
        session=session,
        memberships=memberships,
        audit=audit,
    )


MembershipServiceDep = Annotated[MembershipService, Depends(get_membership_service)]
