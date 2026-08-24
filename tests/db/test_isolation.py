"""Phase 11 acceptance: the suite cannot reach real data.

Every other test here assumes it starts from an empty users table. That only
holds because the suite runs against its own database and rolls each test
back, so those two arrangements are worth asserting directly.
"""

from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.repositories.user_repository import UserRepository
from tests.conftest import APPLICATION_DATABASE, TEST_DATABASE

HASH = "$argon2id$v=19$not-a-real-hash"


def test_the_test_database_is_not_the_application_database() -> None:
    assert TEST_DATABASE.database != APPLICATION_DATABASE.database


def test_settings_point_at_the_test_database() -> None:
    # Not just the fixtures: anything that resolves settings during a test
    # run, including the application's own engine, has to land here too.
    configured = make_url(str(get_settings().database_url))

    assert configured.database == TEST_DATABASE.database


def test_the_applications_own_engine_points_at_the_test_database() -> None:
    assert get_engine().url.database == TEST_DATABASE.database


def test_the_schema_was_built_by_migrations(engine: Engine) -> None:
    with engine.connect() as connection:
        version = connection.scalar(text("SELECT version_num FROM alembic_version"))

    assert version


def test_a_test_starts_with_an_empty_table(user_repository: UserRepository) -> None:
    assert user_repository.count() == 0


def test_this_test_writes_a_user(user_repository: UserRepository) -> None:
    # Paired with the test below: whichever order they run in, neither can
    # see the other's user.
    user_repository.create(name="Ada", email="ada@example.com", hashed_password=HASH)

    assert user_repository.count() == 1


def test_and_this_one_still_starts_empty(user_repository: UserRepository) -> None:
    assert user_repository.count() == 0
    assert user_repository.get_by_email("ada@example.com") is None


def test_a_committed_write_is_still_rolled_back(
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    # The service layer really does commit. The savepoint arrangement is what
    # keeps that from surviving the test.
    user_repository.create(name="Ada", email="ada@example.com", hashed_password=HASH)
    db_session.commit()

    assert user_repository.count() == 1
