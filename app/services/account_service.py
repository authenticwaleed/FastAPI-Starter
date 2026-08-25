from typing import Annotated

from fastapi import Depends

from app.core.exceptions import IncorrectPasswordError, WorkspaceOwnershipError
from app.core.security import verify_password
from app.models.user import User
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.schemas.account import AccountUpdate, PasswordChange
from app.schemas.user import UserUpdate
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
    ) -> None:
        self._users = users
        self._memberships = memberships

    def update(self, user: User, payload: AccountUpdate) -> User:
        return self._users.update_user(
            user.id,
            UserUpdate(name=payload.name, email=payload.email),
        )

    def change_password(self, user: User, payload: PasswordChange) -> None:
        # The bearer token proves who is asking; the current password proves
        # they are the one at the keyboard. Without this second step a
        # stolen token would be enough to lock the owner out of their own
        # account, which is a much worse outcome than the theft itself.
        if not verify_password(payload.current_password, user.hashed_password):
            raise IncorrectPasswordError(user.id)

        # Tokens already issued stay valid until they expire: there is
        # nothing to revoke them with yet, so a change here does not sign
        # anyone out. Refresh tokens and a session list are what make "sign
        # out everywhere" possible, and they are a later phase.
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
) -> AccountService:
    return AccountService(users=users, memberships=memberships)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
