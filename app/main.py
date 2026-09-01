import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContext, SecurityHeaders
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bracket the application's life with a line at each end.

    Neither line carries configuration values: the database URL holds a
    password and the signing key is a secret, so what gets logged is the
    name and the environment and nothing else.
    """
    settings = get_settings()

    logger.info(
        "Starting %s in the %s environment",
        settings.app_name,
        settings.environment,
    )

    yield

    logger.info("Shutting down %s", settings.app_name)

    # By the time this runs uvicorn has stopped accepting connections and
    # waited for the in-flight requests, so closing the pool here is the
    # last thing that happens rather than something a live request can trip
    # over. Without it the database is left to time the connections out.
    get_engine().dispose()


def _add_middleware(app: FastAPI, settings: Settings) -> None:
    # Rejects a request whose Host header the application does not claim to
    # serve, which is what stops host-header poisoning when it sits behind a
    # proxy. With the default ["*"] this passes everything through.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_allow_credentials,
            # Named rather than "*". The API has five verbs and needs two
            # headers; anything beyond that should be a deliberate addition.
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )
    # No origins configured means no cross-origin access, rather than a
    # convenient wildcard nobody remembers to close later.

    # Inside the request context and outside everything else, so that a
    # response refused by the host check carries them too: a browser
    # should be told not to sniff a 400 as readily as a 200.
    app.add_middleware(
        SecurityHeaders,
        # None outside production. A browser told to upgrade this host to
        # HTTPS for two years is one a developer working against
        # http://localhost cannot easily untell.
        hsts_max_age=settings.hsts_max_age_seconds if settings.is_production else None,
    )

    # Added last, which is what puts it outermost: `add_middleware` inserts
    # at the front of the stack, so the last one added is the first one
    # entered. Outermost is where this belongs -- a request refused by the
    # host check above is still a request, and the line saying so should
    # carry an id like every other.
    app.add_middleware(RequestContext)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    `settings` is injectable so a test can build an app configured a
    particular way without touching the cached process-wide settings.
    """
    configure_logging()

    settings = settings or get_settings()

    # `debug` is deliberately not passed through to FastAPI. Starlette's
    # debug mode answers an unhandled exception with the stack trace, in
    # place of the handler registered below, which would ship file paths and
    # internals to whoever triggered the error. The trace is more useful in
    # the log anyway, which is where handle_unexpected_error puts it.
    # settings.debug still controls SQL echo on the engine.
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    _add_middleware(app, settings)
    register_exception_handlers(app)

    app.include_router(
        api_router,
        prefix="/api/v1",
    )

    return app


app = create_app()
