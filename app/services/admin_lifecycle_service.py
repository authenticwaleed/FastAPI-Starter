"""What the platform may do to an account, as opposed to look at.

Phase A4, and the first thing on this surface that changes a customer's
world rather than reading it. Four ideas hold it together.

**It goes through the tenant's own service.** Suspending, closing,
restoring and rescheduling an erasure all end up in `WorkspaceService`,
in the same method a customer's own close uses. A second path that set
the erasure date differently is how a business ends up erased on a day
nobody told them about.

**The customer sees it.** Every act here writes to the business's own
audit log with `by_staff` rather than an actor, so it can never look like
one of their own people did it.

**The destructive ones name their subject.** Closing and erasing take the
workspace's slug in the body. An id is copied from a list; a slug has to
be read and typed, and the difference between those two acts is the
safeguard.

**The erasure is recorded before it happens.** Afterwards there is no
workspace to write about -- which is exactly why `admin_audit_logs` does
not cascade.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConfirmationMismatchError,
    UserNotFoundError,
    WorkspaceNotFoundError,
)
from app.db.session import SessionDep
from app.models.admin_audit_log import AdminAction
from app.models.user import User
from app.models.user_session import SessionEndReason
from app.models.workspace import Workspace
from app.repositories.admin_console_repository import (
    AdminConsoleRepository,
    WorkspaceRow,
)
from app.repositories.user_repository import UserRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.services.admin_audit_service import AdminAuditService, AdminAuditServiceDep
from app.services.admin_workspace_service import AdminConsoleRepositoryDep
from app.services.session_service import UserSessionRepositoryDep
from app.services.staff_service import StaffActor
from app.services.user_service import UserRepositoryDep
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class AdminLifecycleService:
    """Suspending, closing, restoring, erasing -- and the same for a person."""

    def __init__(
        self,
        session: Session,
        console: AdminConsoleRepository,
        workspaces: WorkspaceService,
        users: UserRepository,
        sessions: UserSessionRepository,
        admin_audit: AdminAuditService,
    ) -> None:
        self._session = session
        self._console = console
        self._workspaces = workspaces
        self._users = users
        self._sessions = sessions
        self._admin_audit = admin_audit

    # --- a business --------------------------------------------------------

    def suspend(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        *,
        reason: str,
    ) -> Workspace:
        """Freeze an account: reachable, readable, unchangeable.

        The reason is required and reaches the customer's own log. A
        business that finds its account frozen and cannot see why has to
        open a ticket to be told something the platform already knew.
        """
        row = self._workspace(workspace_id)
        workspace = self._workspaces.suspend(
            row.workspace,
            by_staff=actor.user.email,
            reason=reason,
        )

        self._record(
            actor,
            AdminAction.WORKSPACE_SUSPENDED,
            row,
            {"reason": reason},
        )

        return workspace

    def unsuspend(self, actor: StaffActor, workspace_id: uuid.UUID) -> Workspace:
        row = self._workspace(workspace_id)
        workspace = self._workspaces.unsuspend(row.workspace, by_staff=actor.user.email)

        self._record(actor, AdminAction.WORKSPACE_UNSUSPENDED, row, {})

        return workspace

    def cancel(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        *,
        confirm_slug: str,
    ) -> Workspace:
        """Close an account on the customer's behalf, and start the clock.

        Through the same path a customer's own close takes, so the grace
        period and the erasure job behave identically. The slug in the
        body is what makes this deliberate rather than a mis-click in a
        list of workspaces.
        """
        row = self._confirmed(actor, workspace_id, confirm_slug)
        workspace = self._workspaces.close_for_staff(
            row.workspace,
            by_staff=actor.user.email,
        )

        self._record(
            actor,
            AdminAction.WORKSPACE_CANCELLED,
            row,
            {
                "erase_after": workspace.erase_after.isoformat()
                if workspace.erase_after
                else None
            },
        )

        return workspace

    def restore(self, actor: StaffActor, workspace_id: uuid.UUID) -> Workspace:
        """Bring a closed account back, if its date has not passed."""
        row = self._workspace(workspace_id)
        workspace = self._workspaces.restore(row.workspace, by_staff=actor.user.email)

        self._record(actor, AdminAction.WORKSPACE_RESTORED, row, {})

        return workspace

    def reschedule_erasure(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        *,
        erase_after: datetime,
    ) -> Workspace:
        """Move the date a closed account's records are destroyed.

        Both directions, because both happen: a customer asking to be
        forgotten sooner, and a dispute or a legal hold pushing it out.
        Without this, one of those is done in a database console.
        """
        row = self._workspace(workspace_id)
        was = row.workspace.erase_after
        workspace = self._workspaces.reschedule_erasure(
            row.workspace,
            by_staff=actor.user.email,
            erase_after=erase_after,
        )

        self._record(
            actor,
            AdminAction.WORKSPACE_ERASE_AFTER_CHANGED,
            row,
            {
                "from": was.isoformat() if was else None,
                "to": erase_after.isoformat(),
            },
        )

        return workspace

    def erase_now(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        *,
        confirm_slug: str,
    ) -> None:
        """Destroy a workspace and everything it holds, immediately.

        The most destructive call in the product, and the ordering here
        is the whole of what makes it accountable. The entry is written
        and committed *before* the delete, because afterwards there is no
        workspace to write about -- and it survives the delete because
        this table's workspace reference is nullable and does not
        cascade, with the slug copied beside it.

        A wrong slug is recorded too, as an attempt. Somebody typing the
        wrong name into an erasure is either tired or in the wrong
        window, and both are worth a row.
        """
        row = self._confirmed(actor, workspace_id, confirm_slug)

        self._record(actor, AdminAction.WORKSPACE_ERASED, row, {})
        self._workspaces.erase_now(row.workspace)

    # --- a person ----------------------------------------------------------

    def deactivate(self, actor: StaffActor, user_id: int) -> User:
        """Turn an account off, and sign it out everywhere.

        One transaction, because a deactivated account that stays signed
        in is not deactivated: the access token in a browser keeps
        working until it expires, and the refresh behind it would mint
        another. Both halves or neither.
        """
        user = self._user(user_id)

        self._users.set_active(user, active=False)
        ended = self._sessions.revoke_live_for_user(
            user_id,
            at=datetime.now(UTC),
            reason=SessionEndReason.REVOKED,
        )

        self._told(
            actor,
            AdminAction.USER_DEACTIVATED,
            user,
            {"sessions_ended": ended},
        )

        return user

    def activate(self, actor: StaffActor, user_id: int) -> User:
        """Turn an account back on.

        Nothing is signed back in, which is right: the sessions ended
        when it was deactivated are gone, and coming back means signing
        in -- which is also what proves the account is theirs again.
        """
        user = self._user(user_id)

        self._users.set_active(user, active=True)
        self._told(actor, AdminAction.USER_ACTIVATED, user, {})

        return user

    def revoke_sessions(self, actor: StaffActor, user_id: int) -> int:
        """Sign an account out everywhere, without turning it off.

        The answer to "somebody has my laptop" from a customer who cannot
        reach their own session list. They can sign straight back in,
        which is the difference between this and deactivating.
        """
        user = self._user(user_id)
        ended = self._sessions.revoke_live_for_user(
            user_id,
            at=datetime.now(UTC),
            reason=SessionEndReason.REVOKED,
        )

        self._told(
            actor,
            AdminAction.USER_SESSIONS_REVOKED,
            user,
            {"sessions_ended": ended},
        )

        return ended

    def verify_email(self, actor: StaffActor, user_id: int) -> User:
        """Mark an address confirmed, when delivery failed.

        The narrow case the plan names: mail that will not arrive, at an
        address somebody has confirmed by other means. It records who
        decided that, because the whole point of a verification timestamp
        is that somebody proved something -- and here the proof is a
        staff member's word rather than a link.

        Already-verified is left alone rather than restamped: the
        question the column answers is when it was first proved.
        """
        user = self._user(user_id)

        if user.email_verified_at is None:
            self._users.mark_email_verified(user, datetime.now(UTC))

        self._told(
            actor,
            AdminAction.USER_EMAIL_VERIFIED,
            user,
            {
                "verified_at": user.email_verified_at.isoformat()
                if user.email_verified_at
                else None
            },
        )

        return user

    # --- the steps they share ----------------------------------------------

    def _workspace(self, workspace_id: uuid.UUID) -> WorkspaceRow:
        row = self._console.get_workspace(workspace_id)

        if row is None:
            raise WorkspaceNotFoundError(workspace_id)

        return row

    def _user(self, user_id: int) -> User:
        user = self._console.get_user(user_id)

        if user is None:
            raise UserNotFoundError(user_id)

        return user

    def _confirmed(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        confirm_slug: str,
    ) -> WorkspaceRow:
        """Check that the caller named the workspace they are destroying.

        The attempt is recorded before the refusal, and committed, so a
        mistyped erasure leaves a row rather than nothing. That is the
        one entry in this table written for something that did not
        happen, and the plan asks for it by name.
        """
        row = self._workspace(workspace_id)

        if confirm_slug != row.workspace.slug:
            self._record(
                actor,
                AdminAction.WORKSPACE_ERASE_REFUSED,
                row,
                {"typed": confirm_slug},
            )
            raise ConfirmationMismatchError(workspace_id)

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

    def _told(
        self,
        actor: StaffActor,
        action: AdminAction,
        user: User,
        meta: dict[str, object],
    ) -> None:
        """Record something done to a person rather than to a business.

        No workspace on the entry, which is why this table's workspace
        reference is nullable: an account belongs to no one workspace,
        and pinning it to one it happens to be a member of would be a
        guess.
        """
        self._admin_audit.did(
            actor.logged,
            action,
            target_user_id=user.id,
            meta={"email": user.email, **meta},
        )
        self._session.commit()


def get_admin_lifecycle_service(
    session: SessionDep,
    console: AdminConsoleRepositoryDep,
    workspaces: WorkspaceServiceDep,
    users: UserRepositoryDep,
    sessions: UserSessionRepositoryDep,
    admin_audit: AdminAuditServiceDep,
) -> AdminLifecycleService:
    return AdminLifecycleService(
        session=session,
        console=console,
        workspaces=workspaces,
        users=users,
        sessions=sessions,
        admin_audit=admin_audit,
    )


AdminLifecycleServiceDep = Annotated[
    AdminLifecycleService,
    Depends(get_admin_lifecycle_service),
]
