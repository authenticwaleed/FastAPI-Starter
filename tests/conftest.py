"""Shared fixtures, and the arrangement that keeps the suite off real data.

Importing this module repoints DATABASE_URL at a separate test database
before anything else reads settings. That happens at import time, not in a
fixture, because `get_settings` and `get_engine` are both cached: by the
time a fixture runs, application code may already have resolved them.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session, get_engine, get_session_factory
from app.main import create_app
from app.repositories.user_repository import UserRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _test_database_url() -> URL:
    """Where the suite is allowed to write.

    Never the application's own database: these tests create, update and
    delete users. CI sets TEST_DATABASE_URL; locally the name is derived by
    suffixing the configured one, so a developer needs no extra setup.
    """
    override = os.environ.get("TEST_DATABASE_URL")

    if override:
        return make_url(override)

    url = make_url(str(get_settings().database_url))

    return url.set(database=f"{url.database}_test")


APPLICATION_DATABASE = make_url(str(get_settings().database_url))
TEST_DATABASE = _test_database_url()

if TEST_DATABASE.database == APPLICATION_DATABASE.database:
    raise RuntimeError(
        "The test database must not be the application database: "
        f"both are {APPLICATION_DATABASE.database!r}"
    )

# Swap the setting, then drop every cached value derived from it, so the
# engine the application builds for itself points at the test database too.
# Without this a test that reached the session factory directly, rather than
# through the dependency override below, would write to real data.
os.environ["DATABASE_URL"] = TEST_DATABASE.render_as_string(hide_password=False)
get_settings.cache_clear()
get_engine.cache_clear()
get_session_factory.cache_clear()


def _ensure_database_exists(url: URL) -> None:
    admin = create_engine(
        # CREATE DATABASE cannot run inside a transaction, and it cannot run
        # while connected to the database being created, so this goes
        # through the maintenance database in autocommit.
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )

    try:
        with admin.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            )

            if not exists:
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


def _migrate(url: URL) -> None:
    """Build the schema the way production does, rather than create_all().

    Running the migrations means the suite also proves they still produce a
    schema the models can work against.
    """
    from alembic.config import Config

    from alembic import command

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        url.render_as_string(hide_password=False),
    )

    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    _ensure_database_exists(TEST_DATABASE)
    _migrate(TEST_DATABASE)

    engine = create_engine(TEST_DATABASE, pool_pre_ping=True)

    # A crashed earlier run could have left rows behind. Nothing in the
    # suite should depend on what is in the table when it starts.
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))

    yield engine

    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose writes never survive the test.

    The session joins an outer transaction using create_savepoint, so the
    service layer's real `commit()` calls release a savepoint rather than
    committing to the database. Rolling the outer transaction back at the end
    leaves the table exactly as the test found it, which is what lets every
    test assume it starts from nothing.
    """
    connection = engine.connect()
    transaction = connection.begin()

    session = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def user_repository(db_session: Session) -> UserRepository:
    return UserRepository(db_session)


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A test client sharing the test's rolled-back session."""
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client
