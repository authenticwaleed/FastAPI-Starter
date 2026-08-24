from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db_session, get_engine
from app.main import create_app
from app.repositories.user_repository import UserRepository


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A session whose writes never survive the test.

    The session joins an outer transaction using create_savepoint, so the
    service layer's real `commit()` calls release a savepoint rather than
    committing to the database. Rolling the outer transaction back at the end
    leaves the table exactly as the test found it.
    """
    connection = get_engine().connect()
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
