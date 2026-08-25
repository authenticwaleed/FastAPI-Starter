from logging.config import fileConfig
from typing import Any

from sqlalchemy import Enum, create_engine, pool

# Importing the model package registers every table on Base.metadata.
# Without it autogenerate would compare against an empty schema and happily
# produce a migration that drops everything.
import app.models  # noqa: F401  (imported for the side effect)
from alembic import context
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _enum_constraint_names() -> frozenset[str]:
    """Names of the CHECK constraints that back the enum columns.

    `Enum(native_enum=False, create_constraint=True)` puts the allowed
    values in a CHECK constraint rather than a PostgreSQL type. SQLAlchemy
    attaches that constraint to the table, but Alembic's comparison does
    not pair it with the reflected one, so every autogenerate run reports
    all of them as removed and writes a migration that drops them.

    Dropping them is not cosmetic: it is the difference between a database
    that refuses a fifth workspace status and one that stores anything.
    They are excluded from comparison below, which is correct as well as
    convenient -- the constraint belongs to the column's type, so it is
    created and dropped with the column and is not autogenerate's to
    manage. Read from the models, so adding an enum needs nothing here.
    """
    return frozenset(
        column.type.name
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Enum) and column.type.name
    )


ENUM_CONSTRAINTS = _enum_constraint_names()


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    return not (type_ == "check_constraint" and name in ENUM_CONSTRAINTS)


def get_url() -> str:
    """The database this migration run targets.

    A `sqlalchemy.url` set on the Config wins, which is how the test suite
    points a run at its own database without touching application settings.
    Otherwise it comes from settings, so a plain `alembic upgrade head` uses
    exactly the same configuration as the app and no credentials are
    committed to alembic.ini.
    """
    configured = config.get_main_option("sqlalchemy.url", None)

    return configured or str(get_settings().database_url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it against a database."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    # NullPool: a migration run is short-lived, so pooling buys nothing.
    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type changes, which Alembic ignores by default.
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
