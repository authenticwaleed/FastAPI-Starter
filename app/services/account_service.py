from typing import Annotated

from fastapi import Depends

from app.core.exceptions import IncorrectPasswordError, WorkspaceOwnershipError
from app.core.security import verify_password
from app.models.user import User
from app.models.user_session import SessionEndReason, UserSession
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.schemas.account import AccountUpdate, PasswordChange
from app.schemas.user import UserUpdate
from app.services.session_service import SessionService, SessionServiceDep
from app.services.user_service import UserService, UserServiceDep
from app.services.workspace_service import WorkspaceMembershipRepositoryDep


class AccountService:
    """What a user may do to their own account, and nothing wider.

    Every method takes the authenticated `User` rather than an id. That is
    the whole design: there is no argument here that could name somebody
    else's account, so no request can ask this service to touch a row the
    caller was not already holding. Authorization stops being a check that
    someone might forget to write and becomes a shape the code has.

    The rules themselves -- hashing, the unique email, the transaction --
    stay in UserService. This layer is the self-service boundary around it,
    not a second copy of it.
    """

    def __init__(
        self,
        users: UserService,
        memberships: WorkspaceMembershipRepository,
        sessions: SessionService,
    ) -> None:
        self._users = users
        self._memberships = memberships
        self._sessions = sessions

    def update(self, user: User, payload: AccountUpdate) -> User:
        return self._users.update_user(
            user.id,
            UserUpdate(name=payload.name, email=payload.email),
        )

    def change_password(
        self,
        user: User,
        payload: PasswordChange,
        *,
        keep_session: UserSession | None = None,
    ) -> None:
        # The bearer token proves who is asking; the current password proves
        # they are the one at the keyboard. Without this second step a
        # stolen token would be enough to lock the owner out of their own
        # account, which is a much worse outcome than the theft itself.
        if not verify_password(payload.current_password, user.hashed_password):
            raise IncorrectPasswordError(user.id)

        # Every other session goes. Somebody changing their password
        # because they think it was learned is trying to end the access
        # that knowing it gave -- and a refresh chain that survived the
        # change would be exactly that access, still open, for another
        # month.
        #
        # `keep_session` spares the caller's own. It is the session object
        # the dependency resolved rather than an id off the request, which
        # keeps the rule this service is built on intact: there is no
        # argument here that a caller could substitute.
        #
        # Before the password, not after, and the order is the point.
        # These are two commits -- each service owns its own -- so one of
        # them can land without the other, and the two orders fail
        # differently. Sign out first and a failure leaves the old
        # password working with the sessions closed: an inconvenience,
        # and the caller simply tries again. Change the password first
        # and a failure leaves the new password set with the old
        # sessions still open, which is the exact outcome this is here to
        # prevent.
        self._sessions.revoke_all(
            user,
            reason=SessionEndReason.PASSWORD_CHANGED,
            keep=keep_session.id if keep_session is not None else None,
        )

        # Access tokens already issued for the sessions that just ended
        # stay valid until they expire, which is the one gap short
        # lifetimes are there to bound.
        self._users.update_user(
            user.id,
            UserUpdate(password=payload.new_password),
        )

    def delete(self, user: User) -> None:
        """Delete the account, unless a business still depends on it.

        Closing an account used to affect nobody else. Now that a user can
        own a workspace, the last owner leaving would strand a business
        that no one is able to administer -- its members locked out of
        their own settings, with no route back in. Handing ownership over
        first is the answer, and there is nothing to hand it over with yet,
        so for now this refuses and says so.
        """
        stranded = self._memberships.sole_owned_workspace_ids(user.id)

        if stranded:
            raise WorkspaceOwnershipError(user.id, list(stranded))

        self._users.delete_user(user.id)


def get_account_service(
    users: UserServiceDep,
    memberships: WorkspaceMembershipRepositoryDep,
    sessions: SessionServiceDep,
) -> AccountService:
    return AccountService(users=users, memberships=memberships, sessions=sessions)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
