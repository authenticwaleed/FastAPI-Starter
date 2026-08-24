from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """The process-wide engine, which owns the connection pool.

    Built lazily so importing this module does not require a configured
    database, and cached so every session shares one pool.
    """
    settings = get_settings()

    return create_engine(
        str(settings.database_url),
        echo=settings.debug,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        # Keeps loaded attributes readable after a commit, so a response can
        # still be serialised from an object the service just saved.
        expire_on_commit=False,
    )


def get_db_session() -> Iterator[Session]:
    """Provide a session for the duration of one request.

    Closing the session returns its connection to the pool and rolls back
    anything still pending. Committing stays with the service layer so
    transaction boundaries remain explicit.
    """
    with get_session_factory()() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db_session)]
