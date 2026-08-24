from collections.abc import Sequence

from sqlalchemy import select
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

    def list(self) -> Sequence[User]:
        return self._session.scalars(select(User).order_by(User.id)).all()
