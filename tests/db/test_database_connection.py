"""Phase 1 acceptance: the configured PostgreSQL database is reachable.

These tests need the local PostgreSQL instance described in `.env.example`.
"""

from sqlalchemy import create_engine, text

from app.core.config import get_settings


def test_database_url_uses_a_sqlalchemy_compatible_scheme() -> None:
    scheme = get_settings().database_url.scheme

    # SQLAlchemy 2.x rejects a bare `postgres://` URL; it needs `postgresql`.
    assert scheme.startswith("postgresql")


def test_application_can_connect_to_postgres() -> None:
    engine = create_engine(str(get_settings().database_url))

    try:
        with engine.connect() as connection:
            assert connection.execute(text("select 1")).scalar_one() == 1
    finally:
        engine.dispose()
