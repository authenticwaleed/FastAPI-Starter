import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AppError,
    EmailAlreadyExistsError,
    InactiveUserError,
    IncorrectPasswordError,
    InvalidCredentialsError,
    UserNotFoundError,
)
from app.schemas.errors import ErrorResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Answer:
    """How one kind of domain error looks once it reaches the client."""

    status_code: int
    code: str
    headers: dict[str, str] | None = None


# The single place that knows which domain error is which status code.
# Adding an error means adding a line here, not another try/except in a route.
_ANSWERS: dict[type[AppError], _Answer] = {
    UserNotFoundError: _Answer(status.HTTP_404_NOT_FOUND, "user_not_found"),
    EmailAlreadyExistsError: _Answer(
        status.HTTP_409_CONFLICT,
        "email_already_exists",
    ),
    InvalidCredentialsError: _Answer(
        status.HTTP_401_UNAUTHORIZED,
        "invalid_credentials",
        # RFC 9110 requires a 401 to name the scheme the client should use.
        {"WWW-Authenticate": "Bearer"},
    ),
    InactiveUserError: _Answer(status.HTTP_403_FORBIDDEN, "inactive_user"),
    IncorrectPasswordError: _Answer(
        status.HTTP_400_BAD_REQUEST,
        "incorrect_password",
    ),
}

_UNEXPECTED = _Answer(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error")


def _body(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"detail": detail, "code": code, **extra}


def _answer_for(exc: AppError) -> _Answer:
    # Walk the MRO so a future subclass inherits its parent's answer instead
    # of silently falling through to a 500.
    for error_type in type(exc).__mro__:
        answer = _ANSWERS.get(error_type)

        if answer is not None:
            return answer

    return _UNEXPECTED


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    answer = _answer_for(exc)

    # str(exc) may carry context the response must not, which is exactly why
    # one goes to the log and the other to the client.
    logger.warning(
        "%s %s failed: %s",
        request.method,
        request.url.path,
        exc,
    )

    return JSONResponse(
        status_code=answer.status_code,
        content=_body(answer.code, exc.detail),
        headers=answer.headers,
    )


async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Reshape FastAPI's 422 so it matches every other error.

    Its native body is a bare list under `detail`, where every other failure
    puts a string there. The per-field errors move to `errors`.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=_body(
            "validation_error",
            "Request validation failed",
            errors=jsonable_encoder(exc.errors()),
        ),
    )


async def handle_http_exception(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Cover the errors the framework raises rather than the application.

    An unknown path or a wrong method never reaches a route, so without this
    those would be the only responses with a different shape.
    """
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"

    return JSONResponse(
        status_code=exc.status_code,
        content=_body("http_error", detail),
        headers=getattr(exc, "headers", None),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort for anything not raised deliberately.

    The client is told nothing beyond "it broke": a stack trace or a driver
    message would leak how the application is built. The trace goes to the
    log, where it belongs.
    """
    logger.exception(
        "Unhandled error on %s %s",
        request.method,
        request.url.path,
    )

    return JSONResponse(
        status_code=_UNEXPECTED.status_code,
        content=_body(_UNEXPECTED.code, "Internal server error"),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, handle_unexpected_error)


def _documented(status_code: int, description: str) -> dict[int | str, dict[str, Any]]:
    return {status_code: {"model": ErrorResponse, "description": description}}


# Routes no longer raise these by hand, so OpenAPI can no longer infer them.
# Spreading the relevant ones into a route's `responses` keeps the docs true.
BAD_REQUEST = _documented(
    status.HTTP_400_BAD_REQUEST,
    "Current password is incorrect",
)
CONFLICT = _documented(status.HTTP_409_CONFLICT, "Email already registered")
UNAUTHORISED = _documented(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
FORBIDDEN = _documented(status.HTTP_403_FORBIDDEN, "Inactive user")
