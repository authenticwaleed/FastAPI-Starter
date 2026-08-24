from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionDep
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


class EmailAlreadyExistsError(Exception):
    """A user was created with an email address that is already taken.

    Deliberately not an HTTPException: the service should not know about
    status codes. Phase 9 moves this to a central exceptions module with a
    matching handler.
    """

    def __init__(self, email: str) -> None:
        super().__init__(f"Email already registered: {email}")
        self.email = email


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

    def get_user(self, user_id: int) -> User | None:
        return self._repository.get(user_id)

    def list_users(self) -> Sequence[User]:
        return self._repository.list()


def get_user_repository(session: SessionDep) -> UserRepository:
    return UserRepository(session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_user_service(
    session: SessionDep,
    repository: UserRepositoryDep,
) -> UserService:
    return UserService(session=session, repository=repository)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
