"""Phase 3 acceptance: the User table model.

These tests inspect the mapping and the generated DDL. They never touch a
live database, because creating the table is Alembic's job in Phase 4.
"""

from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.models.user import User
from app.schemas.user import UserRead


def test_user_table_is_registered_on_the_shared_metadata() -> None:
    assert User.__tablename__ == "users"
    assert "users" in Base.metadata.tables


def test_primary_key_is_id() -> None:
    assert [column.name for column in inspect(User).primary_key] == ["id"]


def test_email_is_unique() -> None:
    assert User.__table__.c.email.unique is True

    # The unique constraint is what Postgres indexes; declaring a separate
    # index as well would duplicate it.
    assert User.__table__.indexes == set()


def test_every_column_is_not_nullable() -> None:
    for name in (
        "name",
        "email",
        "hashed_password",
        "is_active",
        "created_at",
        "updated_at",
    ):
        assert User.__table__.c[name].nullable is False, name


def test_password_is_stored_only_as_a_hash() -> None:
    columns = set(User.__table__.c.keys())

    assert "hashed_password" in columns
    assert "password" not in columns


def test_password_hash_is_never_exposed_by_the_read_schema() -> None:
    assert "hashed_password" not in UserRead.model_fields
    assert "password" not in UserRead.model_fields


def test_timestamps_are_timezone_aware_and_defaulted() -> None:
    for name in ("created_at", "updated_at"):
        column = User.__table__.c[name]

        assert column.type.timezone is True, name
        assert column.server_default is not None, name

    # Only updated_at is refreshed on write.
    assert User.__table__.c.created_at.onupdate is None
    assert User.__table__.c.updated_at.onupdate is not None


def test_model_compiles_to_valid_postgresql_ddl() -> None:
    ddl = str(CreateTable(User.__table__).compile(dialect=postgresql.dialect()))

    assert "PRIMARY KEY (id)" in ddl
    assert "UNIQUE (email)" in ddl
    assert "hashed_password VARCHAR(255) NOT NULL" in ddl
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in ddl


def test_repr_does_not_leak_the_password_hash() -> None:
    user = User(id=1, name="Ada", email="ada@example.com", hashed_password="secret-hash")

    assert "secret-hash" not in repr(user)
