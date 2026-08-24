from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionDep
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate


class EmailAlreadyExistsError(Exception):
    """A user was created with an email address that is already taken.

    Deliberately not an HTTPException: the service should not know about
    status codes. Phase 9 moves this to a central exceptions module with a
    matching handler.
    """

    def __init__(self, email: str) -> None:
        super().__init__(f"Email already registered: {email}")
        self.email = email


class UserNotFoundError(Exception):
    """No user exists with the requested id.

    Like the error above, this stays free of HTTP concerns and becomes a 404
    only at the route boundary.
    """

    def __init__(self, user_id: int) -> None:
        super().__init__(f"User not found: {user_id}")
        self.user_id = user_id


class UserService:
    """Business rules for users. Owns the transaction, not the queries."""

    def __init__(self, session: Session, repository: UserRepository) -> None:
        self._session = session
        self._repository = repository

    def create_user(self, payload: UserCreate) -> User:
        if self._repository.get_by_email(payload.email) is not None:
            raise EmailAlreadyExistsError(payload.email)

        try:
            user = self._repository.create(
                name=payload.name,
                email=payload.email,
                hashed_password=hash_password(payload.password),
            )
            self._session.commit()
        except IntegrityError as exc:
            # Two concurrent requests can both pass the check above; the
            # unique constraint is what actually settles it.
            self._session.rollback()
            raise EmailAlreadyExistsError(payload.email) from exc

        return user

    def get_user(self, user_id: int) -> User:
        user = self._repository.get(user_id)

        if user is None:
            raise UserNotFoundError(user_id)

        return user

    def list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[User], int]:
        """Return one page of users together with the total user count.

        Pages are 1-based because that is what a client asks for; the offset
        arithmetic belongs here rather than in the route.
        """
        users = self._repository.list(
            limit=page_size,
            offset=(page - 1) * page_size,
        )

        return users, self._repository.count()

    def update_user(self, user_id: int, payload: UserUpdate) -> User:
        user = self.get_user(user_id)
        # Read before anything is mutated, so it survives a rollback below
        # without needing to reload the row.
        current_email = user.email

        if payload.email is not None and payload.email != current_email:
            if self._repository.get_by_email(payload.email) is not None:
                raise EmailAlreadyExistsError(payload.email)

        try:
            self._repository.update(
                user,
                name=payload.name,
                email=payload.email,
                hashed_password=(
                    hash_password(payload.password)
                    if payload.password is not None
                    else None
                ),
            )
            self._session.commit()
        except IntegrityError as exc:
            # Same race as in create_user: the unique email index is the only
            # constraint an update can break, so a new address must have been
            # supplied for us to get here.
            self._session.rollback()
            raise EmailAlreadyExistsError(payload.email or current_email) from exc

        return user

    def delete_user(self, user_id: int) -> None:
        self._repository.delete(self.get_user(user_id))
        self._session.commit()


def get_user_repository(session: SessionDep) -> UserRepository:
    return UserRepository(session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_user_service(
    session: SessionDep,
    repository: UserRepositoryDep,
) -> UserService:
    return UserService(session=session, repository=repository)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
