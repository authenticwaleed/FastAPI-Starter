from collections.abc import Sequence
from datetime import datetime

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

    def set_active(self, user: User, *, active: bool) -> User:
        """Turn an account off, or back on.

        Its own method for the reason `clear_email_verification` is one:
        `update` treats `None` as "leave this alone", so there is no value
        it could be passed that means "set this to false".

        Nothing here signs the account out. That is deliberate and it is
        the caller's job, in the same transaction -- a deactivated account
        that stays signed in is not deactivated, and pairing the two here
        would hide a decision the platform surface has to make out loud.
        """
        user.is_active = active
        self._session.flush()

        return user

    def mark_email_verified(self, user: User, at: datetime) -> User:
        """Record that somebody proved they read mail at this address."""
        user.email_verified_at = at
        self._session.flush()

        return user

    def clear_email_verification(self, user: User) -> User:
        """Undo that, because the address it was about is no longer theirs.

        Separate from `update` above rather than folded into it. There,
        `None` means "leave this alone" for every field, so there is no
        value it could be passed that means "set this back to null".
        """
        user.email_verified_at = None
        self._session.flush()

        return user

    def delete(self, user: User) -> None:
        self._session.delete(user)
        self._session.flush()
