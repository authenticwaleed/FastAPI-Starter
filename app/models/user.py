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

    # When somebody proved they read mail at this address, or null if
    # nobody has yet. A timestamp rather than a flag: "verified when?" is
    # the question support actually asks, and a flag cannot answer it.
    #
    # Cleared when the address changes, because what was proved was about
    # the old one. Nothing is gated on it yet -- an unverified account can
    # do everything a verified one can -- so today it is a fact the API
    # reports rather than a permission it enforces.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
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
