"""Phase 16 acceptance: the process starts and stops cleanly."""

from fastapi.testclient import TestClient

from app.db.session import get_engine
from app.main import create_app


def test_shutdown_disposes_the_connection_pool() -> None:
    # dispose() replaces the pool rather than emptying it, so a new pool
    # object is the observable evidence that the old one was closed.
    engine = get_engine()
    engine.connect().close()
    pool_before = engine.pool

    with TestClient(create_app()):
        pass

    assert engine.pool is not pool_before


def test_the_engine_still_works_after_a_shutdown() -> None:
    # Disposing is not destroying: the next request builds a fresh pool.
    # Without this the suite's own later tests would be the ones to find out.
    with TestClient(create_app()):
        pass

    with get_engine().connect() as connection:
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1
