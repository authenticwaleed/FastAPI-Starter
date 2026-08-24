"""Phase 2 acceptance: engine, session factory and session dependency.

These tests need the local PostgreSQL instance described in `.env.example`.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionDep, get_engine


def test_engine_is_built_from_settings() -> None:
    url = get_engine().url
    configured = make_url(str(get_settings().database_url))

    assert url.drivername == configured.drivername
    assert url.database == configured.database


def test_engine_is_shared_across_calls() -> None:
    # One pool per process, not one per caller.
    assert get_engine() is get_engine()


def test_session_can_be_injected_into_an_endpoint() -> None:
    app = FastAPI()

    # A sync endpoint, so FastAPI runs this blocking session in a threadpool
    # instead of stalling the event loop.
    @app.get("/db-check")
    def db_check(session: SessionDep) -> dict[str, int]:
        return {"result": session.execute(text("select 1")).scalar_one()}

    with TestClient(app) as client:
        response = client.get("/db-check")

    assert response.status_code == 200
    assert response.json() == {"result": 1}


def test_session_is_closed_and_its_connection_returned() -> None:
    engine = get_engine()
    app = FastAPI()

    @app.get("/db-check")
    def db_check(session: SessionDep) -> dict[str, int]:
        session.execute(text("select 1"))
        return {"checked_out": engine.pool.checkedout()}

    with TestClient(app) as client:
        response = client.get("/db-check")

    assert response.json()["checked_out"] == 1
    assert engine.pool.checkedout() == 0


def test_session_is_rolled_back_when_an_endpoint_fails() -> None:
    engine = get_engine()
    app = FastAPI()
    captured: list[Session] = []

    @app.get("/boom")
    def boom(session: SessionDep) -> None:
        captured.append(session)
        session.execute(text("select 1"))
        raise RuntimeError("endpoint blew up")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert not captured[0].in_transaction()
    assert engine.pool.checkedout() == 0
