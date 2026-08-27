from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import EmailAlreadyExistsError, UserNotFoundError
from app.core.security import hash_password
from app.db.session import SessionDep
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate


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

        if (
            payload.email is not None
            and payload.email != current_email
            and self._repository.get_by_email(payload.email) is not None
        ):
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

            if payload.email is not None and payload.email != current_email:
                # A new address is an unconfirmed one. What was proved was
                # that somebody read mail at the old address, and carrying
                # that over would make the flag mean nothing at all --
                # anybody could become "verified" at any address by
                # changing to it. Confirming the new one starts again at
                # /auth/resend-verification.
                self._repository.clear_email_verification(user)

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
