from typing import Annotated

from fastapi import Depends
from jwt import InvalidTokenError

from app.core.exceptions import InactiveUserError, InvalidCredentialsError
from app.core.security import (
    create_access_token,
    decode_access_token,
    unusable_hash,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, Token
from app.schemas.user import UserCreate
from app.services.user_service import (
    UserRepositoryDep,
    UserService,
    UserServiceDep,
)


class AuthService:
    """Registration, login, and answering "who does this token belong to?".

    Password hashing and the unique-email rule stay in UserService; what
    this service owns is the credential check and the token.
    """

    def __init__(self, users: UserService, repository: UserRepository) -> None:
        self._users = users
        self._repository = repository

    def register(self, payload: UserCreate) -> User:
        # Registration is user creation. Delegating keeps one place that
        # hashes the password and enforces the unique email, rather than a
        # second path that could drift from it.
        return self._users.create_user(payload)

    def authenticate(self, email: str, password: str) -> User:
        user = self._repository.get_by_email(email)

        if user is None:
            # Verify against a hash nothing matches. Returning early here
            # instead would make an unknown address measurably faster than a
            # wrong password, which is enough to enumerate accounts.
            verify_password(password, unusable_hash())
            raise InvalidCredentialsError

        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError

        if not user.is_active:
            raise InactiveUserError(user.id)

        return user

    def login(self, credentials: LoginRequest) -> Token:
        user = self.authenticate(credentials.email, credentials.password)

        # The subject is the id rather than the email, so changing an address
        # does not invalidate live tokens and the token carries no personal
        # data for whoever ends up holding it.
        return Token(access_token=create_access_token(str(user.id)))

    def current_user(self, token: str) -> User:
        try:
            user_id = int(decode_access_token(token))
        except (InvalidTokenError, ValueError):
            raise InvalidCredentialsError(
                detail="Invalid or expired token",
            ) from None

        user = self._repository.get(user_id)

        if user is None:
            # Correctly signed, but for an account that has since been
            # deleted. The token outlives the row it points at.
            raise InvalidCredentialsError(detail="Invalid or expired token")

        if not user.is_active:
            raise InactiveUserError(user.id)

        return user


def get_auth_service(
    users: UserServiceDep,
    repository: UserRepositoryDep,
) -> AuthService:
    return AuthService(users=users, repository=repository)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
