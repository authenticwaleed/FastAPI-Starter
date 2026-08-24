from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Every query against the users table lives here.

    Methods flush rather than commit, so the caller decides where a
    transaction ends and several operations can share one.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, name: str, email: str, hashed_password: str) -> User:
        user = User(
            name=name,
            email=email,
            hashed_password=hashed_password,
        )

        self._session.add(user)
        # Flush so the database assigns the primary key and defaults, while
        # leaving the transaction open.
        self._session.flush()

        return user

    def get(self, user_id: int) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self._session.scalar(select(User).where(User.email == email))

    def list(self, *, limit: int, offset: int) -> Sequence[User]:
        """One page of users, oldest first.

        `limit` and `offset` are required rather than defaulted: an unbounded
        SELECT over a growing table should never be the easy option.
        """
        return self._session.scalars(
            select(User).order_by(User.id).limit(limit).offset(offset)
        ).all()

    def count(self) -> int:
        """How many users exist, for the pagination total."""
        return self._session.scalar(select(func.count()).select_from(User)) or 0

    def update(
        self,
        user: User,
        *,
        name: str | None = None,
        email: str | None = None,
        hashed_password: str | None = None,
    ) -> User:
        """Apply the fields that were supplied and leave the rest untouched.

        `None` means "no change" rather than "set to null", which is
        unambiguous here because all three columns are NOT NULL. If nothing
        changes, the flush emits no UPDATE and `updated_at` stays put.
        """
        if name is not None:
            user.name = name

        if email is not None:
            user.email = email

        if hashed_password is not None:
            user.hashed_password = hashed_password

        self._session.flush()

        return user

    def delete(self, user: User) -> None:
        self._session.delete(user)
        self._session.flush()
