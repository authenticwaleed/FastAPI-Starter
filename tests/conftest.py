"""Shared fixtures, and the arrangement that keeps the suite off real data.

Importing this module repoints DATABASE_URL at a separate test database
before anything else reads settings. That happens at import time, not in a
fixture, because `get_settings` and `get_engine` are both cached: by the
time a fixture runs, application code may already have resolved them.
"""

import os
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.api.dependencies.rate_limit import get_rate_limiter, limits_from
from app.core.config import get_settings
from app.core.encryption import _cipher
from app.core.rate_limit import RateLimiter
from app.db.session import get_db_session, get_engine, get_session_factory
from app.main import create_app
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.ecommerce_account_repository import (
    EcommerceAccountRepository,
)
from app.repositories.message_repository import MessageRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.repositories.user_token_repository import UserTokenRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.repositories.workspace_invitation_repository import (
    WorkspaceInvitationRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.ai_dispatch import get_session_source
from app.services.ai_response_service import get_reply_writer
from app.services.ecommerce_service import get_ecommerce_provider
from app.services.email_dispatch import get_email_sender
from app.services.knowledge_service import get_embedding_provider
from app.services.whatsapp_service import get_messaging_provider
from tests.support.ecommerce import FakeEcommerceProvider
from tests.support.email import FakeEmailSender
from tests.support.knowledge import FakeEmbeddingProvider, FakeReplyWriter
from tests.support.messaging import FakeMessagingProvider

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
# Provider tokens are encrypted before they are stored, so the suite needs
# a key. Set here rather than in a fixture, for the same reason the
# database URL is: settings are cached, and by the time a fixture runs
# something may already have read them. A fixed value, because it protects
# nothing -- every row it ever touches is rolled back.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "8GkQ0DPTPzY3RtsDcRUv0YyBFqPLmPqXbYtdzwXQvbA=",
)
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "a-verify-token-for-tests")
os.environ.setdefault("WHATSAPP_APP_SECRET", "an-app-secret-for-tests")
# The storefront's credentials, for the same reason and with the same
# force: they sign an OAuth callback and every webhook, and the tests
# that exercise those have to be able to produce a signature the adapter
# will accept.
os.environ.setdefault("SHOPIFY_API_KEY", "a-shopify-key-for-tests")
os.environ.setdefault("SHOPIFY_API_SECRET", "a-shopify-secret-for-tests")

os.environ["DATABASE_URL"] = TEST_DATABASE.render_as_string(hide_password=False)
get_settings.cache_clear()
_cipher.cache_clear()
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
    # suite should depend on what is in the tables when it starts.
    #
    # Named rather than relying on CASCADE to reach them from users: a
    # table that stops referencing users would quietly stop being cleaned,
    # and the failure would look like a flaky test somewhere else.
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE conversation_events, ai_response_logs, "
                "knowledge_chunks, "
                "knowledge_documents, knowledge_sources, "
                "product_variants, products, orders, "
                "messages, conversations, contacts, "
                "whatsapp_accounts, ecommerce_accounts, workspace_invitations, "
                "workspace_memberships, workspaces, "
                "refresh_tokens, user_sessions, user_tokens, users "
                "RESTART IDENTITY CASCADE"
            )
        )

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
def user_session_repository(db_session: Session) -> UserSessionRepository:
    return UserSessionRepository(db_session)


@pytest.fixture
def user_token_repository(db_session: Session) -> UserTokenRepository:
    return UserTokenRepository(db_session)


@pytest.fixture
def ecommerce_account_repository(
    db_session: Session,
) -> EcommerceAccountRepository:
    return EcommerceAccountRepository(db_session)


@pytest.fixture
def workspace_repository(db_session: Session) -> WorkspaceRepository:
    return WorkspaceRepository(db_session)


@pytest.fixture
def membership_repository(db_session: Session) -> WorkspaceMembershipRepository:
    return WorkspaceMembershipRepository(db_session)


@pytest.fixture
def invitation_repository(db_session: Session) -> WorkspaceInvitationRepository:
    return WorkspaceInvitationRepository(db_session)


@pytest.fixture
def contact_repository(db_session: Session) -> ContactRepository:
    return ContactRepository(db_session)


@pytest.fixture
def conversation_repository(db_session: Session) -> ConversationRepository:
    return ConversationRepository(db_session)


@pytest.fixture
def message_repository(db_session: Session) -> MessageRepository:
    return MessageRepository(db_session)


@pytest.fixture
def whatsapp_account_repository(db_session: Session) -> WhatsAppAccountRepository:
    return WhatsAppAccountRepository(db_session)


@pytest.fixture
def messaging_provider() -> FakeMessagingProvider:
    return FakeMessagingProvider()


@pytest.fixture
def embedding_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def reply_writer() -> FakeReplyWriter:
    return FakeReplyWriter()


@pytest.fixture
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def ecommerce_provider() -> FakeEcommerceProvider:
    return FakeEcommerceProvider()


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """A limiter that counts nothing, which is what most tests want.

    Limits are real state that outlives a request, so a suite running
    against a live one would have tests interfering with each other --
    and an unrelated test would start failing the day somebody added a
    sixth login to it. The tests that are about limiting ask for this
    fixture and turn it on, with numbers of their own.
    """
    return RateLimiter(limits=limits_from(get_settings()), enabled=False)


@pytest.fixture
def client(
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
    embedding_provider: FakeEmbeddingProvider,
    reply_writer: FakeReplyWriter,
    email_sender: FakeEmailSender,
    ecommerce_provider: FakeEcommerceProvider,
    rate_limiter: RateLimiter,
) -> Iterator[TestClient]:
    """A test client sharing the test's rolled-back session.

    Every outbound provider is replaced here rather than in the tests that
    happen to think about it. The suite's rule is that nothing in it
    reaches the network, and a rule kept by each test remembering to keep
    it is a rule that a test added next month breaks -- quietly, because a
    real call fails in a way that looks like the feature failing.

    A test that cares what was sent asks for the same fixture and reads
    the fake; a test that does not care gets the guarantee for free.
    """
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session
    # Work scheduled by a request runs on a session of its own, which in
    # production is right and here would be a second connection that
    # cannot see this test's uncommitted transaction -- and whose own
    # writes would outlive it. Handing over the test's session, without
    # closing it, puts background work inside the same rollback as
    # everything else.
    app.dependency_overrides[get_session_source] = lambda: (
        lambda: nullcontext(db_session)
    )
    app.dependency_overrides[get_messaging_provider] = lambda: messaging_provider
    app.dependency_overrides[get_embedding_provider] = lambda: embedding_provider
    app.dependency_overrides[get_reply_writer] = lambda: reply_writer
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    app.dependency_overrides[get_ecommerce_provider] = lambda: ecommerce_provider
    app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter

    with TestClient(app) as test_client:
        yield test_client
