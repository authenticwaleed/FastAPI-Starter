"""Looking up a person, rather than a business.

The other half of the console, and it is separate for the same reason
the routes are: a support ticket arrives from either direction. Sometimes
it names a business, and sometimes it is somebody who cannot sign in and
has no idea which workspaces they belong to.

Metadata only, like everything else in this phase. An account's name,
whether it is active, which workspaces it is in, and where it is signed
in -- never a password hash, never a token, and nothing about the
customers of the businesses it belongs to.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import UserNotFoundError
from app.db.session import SessionDep
from app.models.admin_audit_log import AdminAction
from app.models.user import User
from app.models.user_session import UserSession
from app.models.workspace import Workspace
from app.models.workspace_membership import WorkspaceMembership
from app.repositories.admin_console_repository import AdminConsoleRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.services.admin_audit_service import AdminAuditService, AdminAuditServiceDep
from app.services.admin_workspace_service import AdminConsoleRepositoryDep
from app.services.session_service import UserSessionRepositoryDep
from app.services.staff_service import StaffActor


class AdminUserService:
    """One account, from the outside.

    Reads are recorded here as they are everywhere on this surface, and
    they name the account that was looked at. That matters more than it
    might: a staff member reading one customer's own record is exactly
    the act that has to be reviewable, and there is no workspace on the
    entry to attach it to -- so `target_user_id` carries it instead.
    """

    def __init__(
        self,
        session: Session,
        console: AdminConsoleRepository,
        admin_audit: AdminAuditService,
        sessions: UserSessionRepository,
    ) -> None:
        self._session = session
        self._console = console
        self._admin_audit = admin_audit
        self._sessions = sessions

    def search(
        self,
        actor: StaffActor,
        *,
        term: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[Sequence[User], int]:
        """Accounts by address or name, paged.

        What was searched for is recorded with the search. A row saying
        somebody ran a search says nothing; a row saying they searched
        every address at one company is the beginning of an answer.
        """
        found = self._console.search_users(
            term=term,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = self._console.count_users(term=term)

        self._admin_audit.did(
            actor.logged,
            AdminAction.USERS_SEARCHED,
            meta={"term": term, "results": total},
        )
        self._session.commit()

        return found, total

    def read(
        self,
        actor: StaffActor,
        user_id: int,
    ) -> tuple[
        User,
        list[tuple[WorkspaceMembership, Workspace]],
        Sequence[UserSession],
    ]:
        """One account, the workspaces it belongs to, and where it is signed in.

        The three things a "I cannot get in" ticket needs, and they are
        fetched together because they are read together: whether the
        account is active, whether it is actually in the business it
        claims to be, and whether anything is signed in at all.

        Live sessions only. A list of sign-ins that have already lapsed
        is not what the question was, and the row somebody is about to
        act on -- in Phase A4, which can end them -- is always a live one.

        An account with no workspaces and no sessions answers cleanly,
        with two empty lists. That is a real state and a common one: it
        is what somebody who registered and never finished looks like.
        """
        user = self._console.get_user(user_id)

        if user is None:
            # Honest, unlike the tenant surface's refusals, and it can
            # afford to be: whoever is asking has already proved they are
            # staff and is already being recorded.
            raise UserNotFoundError(user_id)

        memberships = self._console.memberships_for_user(user_id)
        sessions = self._sessions.list_live_for_user(user_id, datetime.now(UTC))

        self._admin_audit.did(
            actor.logged,
            AdminAction.USER_READ,
            target_user_id=user_id,
            meta={
                "email": user.email,
                "workspaces": len(memberships),
                "sessions": len(sessions),
            },
        )
        self._session.commit()

        return user, memberships, sessions


def get_admin_user_service(
    session: SessionDep,
    console: AdminConsoleRepositoryDep,
    admin_audit: AdminAuditServiceDep,
    sessions: UserSessionRepositoryDep,
) -> AdminUserService:
    return AdminUserService(
        session=session,
        console=console,
        admin_audit=admin_audit,
        sessions=sessions,
    )


AdminUserServiceDep = Annotated[
    AdminUserService,
    Depends(get_admin_user_service),
]
