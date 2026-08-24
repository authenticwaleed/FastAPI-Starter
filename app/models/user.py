from datetime import datetime

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(100))

    # RFC 5321 caps an address at 320 characters. `unique=True` already gives
    # Postgres the index it needs, so adding index=True would only create a
    # second, redundant one.
    email: Mapped[str] = mapped_column(String(320), unique=True)

    # Only ever a hash. The plain password is request input and nothing else,
    # and it is never written to this column or returned by the API.
    hashed_password: Mapped[str] = mapped_column(String(255))

    is_active: Mapped[bool] = mapped_column(
        default=True,
        server_default=text("true"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # `onupdate` is applied by SQLAlchemy when it emits an UPDATE. A statement
    # issued outside the ORM would bypass it; a database trigger would be the
    # stricter option if that ever matters.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, email={self.email!r})"
