from enum import StrEnum

from sqlalchemy import Enum


def enum_column(enum_type: type[StrEnum], *, name: str) -> Enum:
    """A column holding one of an enum's values, checked by the database.

    Stored as text with a CHECK constraint rather than as a PostgreSQL
    ENUM type. A native enum can only be extended with ALTER TYPE, never
    reduced, and every change to one is a migration that cannot run inside
    a transaction with anything else. A CHECK constraint is dropped and
    recreated like any other, which is what makes a vocabulary that is
    still settling -- roles, statuses -- cheap to change.

    `values_callable` is what stores "owner" rather than "OWNER":
    SQLAlchemy persists enum *names* by default, and the names here are
    an implementation detail of the Python side.
    """
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        # False by default for a non-native enum, which would leave the
        # column an unchecked VARCHAR.
        create_constraint=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )
