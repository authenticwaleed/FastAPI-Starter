from functools import lru_cache
from itertools import count

from app.schemas.user import UserCreate, UserRead


class UserService:
    """Business logic for users.

    Storage is an in-memory dictionary, so users do not survive a restart and
    are not shared between workers. Phase 1 replaces this with PostgreSQL
    behind a repository layer.
    """

    def __init__(self) -> None:
        self._users: dict[int, UserRead] = {}
        self._next_id = count(1)

    def create_user(self, payload: UserCreate) -> UserRead:
        user = UserRead(
            id=next(self._next_id),
            **payload.model_dump(),
        )
        self._users[user.id] = user
        return user

    def get_user(self, user_id: int) -> UserRead | None:
        return self._users.get(user_id)

    def list_users(self) -> list[UserRead]:
        return list(self._users.values())


@lru_cache
def get_user_service() -> UserService:
    return UserService()
