import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AlreadyAMemberError,
    AppError,
    AutomationAlreadyExistsError,
    AutomationNotFoundError,
    ContactAlreadyExistsError,
    ContactNotFoundError,
    ConversationAlreadyOpenError,
    ConversationClosedError,
    ConversationNotFoundError,
    DocumentAlreadyIngestedError,
    EcommerceProviderError,
    EmailAlreadyExistsError,
    EmailDeliveryError,
    EmbeddingProviderError,
    EncryptionUnavailableError,
    InactiveUserError,
    IncorrectPasswordError,
    InsufficientWorkspaceRoleError,
    InvalidAutomationSettingsError,
    InvalidCredentialsError,
    InvalidDateRangeError,
    InvalidRefreshTokenError,
    InvalidVerificationTokenError,
    InvalidWebhookError,
    InvitationAlreadyAcceptedError,
    InvitationExpiredError,
    InvitationNotFoundError,
    InvitationNotYoursError,
    KnowledgeDocumentNotFoundError,
    KnowledgeSourceNotFoundError,
    LastOwnerError,
    MembershipNotFoundError,
    MessagingProviderError,
    NotificationNotFoundError,
    OrderAlreadyExistsError,
    OrderNotConfirmableError,
    OrderNotFoundError,
    PendingInvitationExistsError,
    ProductConflictError,
    ProductNotFoundError,
    RateLimitExceededError,
    RefreshTokenReusedError,
    ReplyProviderError,
    SessionNotFoundError,
    SlugAlreadyExistsError,
    StorefrontAlreadyConnectedError,
    StorefrontNotConnectedError,
    UnknownTimezoneError,
    UnreadableDocumentError,
    UnsupportedDocumentTypeError,
    UserNotFoundError,
    WhatsAppAlreadyConnectedError,
    WhatsAppNotConnectedError,
    WorkspaceNotFoundError,
    WorkspaceOwnershipError,
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
    InvalidRefreshTokenError: _Answer(
        status.HTTP_401_UNAUTHORIZED,
        "invalid_refresh_token",
        {"WWW-Authenticate": "Bearer"},
    ),
    # Its own code although it subclasses the one above, because a client
    # has something to do about this one: stop retrying, throw the tokens
    # away and send the user back to the login screen.
    RefreshTokenReusedError: _Answer(
        status.HTTP_401_UNAUTHORIZED,
        "refresh_token_reused",
        {"WWW-Authenticate": "Bearer"},
    ),
    SessionNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "session_not_found",
    ),
    # 400 rather than 401: nobody was authenticating. A link that has
    # been used or has aged out is a bad argument to this endpoint, and
    # answering 401 would send a client that is holding a perfectly good
    # session back to the login screen.
    InvalidVerificationTokenError: _Answer(
        status.HTTP_400_BAD_REQUEST,
        "invalid_verification_token",
    ),
    # 502 for the reason the other outbound failures get one: this
    # application worked and the thing it depends on did not. No route
    # returns it today -- every send happens after its response -- and it
    # is mapped so that the day one does, it is not a 500.
    EmailDeliveryError: _Answer(
        status.HTTP_502_BAD_GATEWAY,
        "email_delivery_error",
    ),
    # Retry-After is not declared here because it is not the same for
    # every instance -- the error carries its own, through `headers()`.
    RateLimitExceededError: _Answer(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limit_exceeded",
    ),
    WorkspaceNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "workspace_not_found",
    ),
    SlugAlreadyExistsError: _Answer(
        status.HTTP_409_CONFLICT,
        "slug_already_exists",
    ),
    InsufficientWorkspaceRoleError: _Answer(
        status.HTTP_403_FORBIDDEN,
        "insufficient_workspace_role",
    ),
    WorkspaceOwnershipError: _Answer(
        status.HTTP_409_CONFLICT,
        "workspace_ownership_required",
    ),
    MembershipNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "membership_not_found",
    ),
    LastOwnerError: _Answer(status.HTTP_409_CONFLICT, "last_owner"),
    InvitationNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "invitation_not_found",
    ),
    # 410 rather than 404: the link was real, and saying so is the
    # difference between "ask for another" and "check the address".
    InvitationExpiredError: _Answer(status.HTTP_410_GONE, "invitation_expired"),
    InvitationAlreadyAcceptedError: _Answer(
        status.HTTP_409_CONFLICT,
        "invitation_already_accepted",
    ),
    InvitationNotYoursError: _Answer(
        status.HTTP_403_FORBIDDEN,
        "invitation_not_yours",
    ),
    AlreadyAMemberError: _Answer(status.HTTP_409_CONFLICT, "already_a_member"),
    ContactNotFoundError: _Answer(status.HTTP_404_NOT_FOUND, "contact_not_found"),
    ProductNotFoundError: _Answer(status.HTTP_404_NOT_FOUND, "product_not_found"),
    ProductConflictError: _Answer(status.HTTP_409_CONFLICT, "product_conflict"),
    OrderNotFoundError: _Answer(status.HTTP_404_NOT_FOUND, "order_not_found"),
    NotificationNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "notification_not_found",
    ),
    AutomationNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "automation_not_found",
    ),
    AutomationAlreadyExistsError: _Answer(
        status.HTTP_409_CONFLICT,
        "automation_already_exists",
    ),
    # 422 rather than 400: the request was well formed and what was
    # inside it did not fit the automation it named, which is the
    # distinction a client needs to know whether to fix the call or the
    # form.
    InvalidAutomationSettingsError: _Answer(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_automation_settings",
    ),
    OrderAlreadyExistsError: _Answer(
        status.HTTP_409_CONFLICT,
        "order_already_exists",
    ),
    OrderNotConfirmableError: _Answer(
        status.HTTP_409_CONFLICT,
        "order_not_confirmable",
    ),
    StorefrontNotConnectedError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "storefront_not_connected",
    ),
    StorefrontAlreadyConnectedError: _Answer(
        status.HTTP_409_CONFLICT,
        "storefront_already_connected",
    ),
    # 502 for the reason the other outbound failures get one: this
    # application worked and the shop it depends on did not. A callback
    # that fails to verify lands here too, which is deliberate -- the
    # alternative is telling whoever forged it exactly what was wrong.
    EcommerceProviderError: _Answer(
        status.HTTP_502_BAD_GATEWAY,
        "ecommerce_provider_error",
    ),
    ContactAlreadyExistsError: _Answer(
        status.HTTP_409_CONFLICT,
        "contact_already_exists",
    ),
    ConversationNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "conversation_not_found",
    ),
    ConversationAlreadyOpenError: _Answer(
        status.HTTP_409_CONFLICT,
        "conversation_already_open",
    ),
    ConversationClosedError: _Answer(
        status.HTTP_409_CONFLICT,
        "conversation_closed",
    ),
    WhatsAppNotConnectedError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "whatsapp_not_connected",
    ),
    WhatsAppAlreadyConnectedError: _Answer(
        status.HTTP_409_CONFLICT,
        "whatsapp_already_connected",
    ),
    InvalidWebhookError: _Answer(
        status.HTTP_403_FORBIDDEN,
        "invalid_webhook_signature",
    ),
    # 502 rather than 500: this application worked, and the thing it
    # depends on did not. The distinction is what stops a provider outage
    # reading as a bug in here.
    MessagingProviderError: _Answer(
        status.HTTP_502_BAD_GATEWAY,
        "messaging_provider_error",
    ),
    EncryptionUnavailableError: _Answer(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "integration_unavailable",
    ),
    PendingInvitationExistsError: _Answer(
        status.HTTP_409_CONFLICT,
        "invitation_already_pending",
    ),
    KnowledgeSourceNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "knowledge_source_not_found",
    ),
    KnowledgeDocumentNotFoundError: _Answer(
        status.HTTP_404_NOT_FOUND,
        "knowledge_document_not_found",
    ),
    DocumentAlreadyIngestedError: _Answer(
        status.HTTP_409_CONFLICT,
        "document_already_ingested",
    ),
    # 422 rather than 400: the request was well formed and the file inside
    # it was not usable, which is the distinction a client needs to decide
    # whether to fix the call or fix the file.
    UnreadableDocumentError: _Answer(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "unreadable_document",
    ),
    UnsupportedDocumentTypeError: _Answer(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "unsupported_document_type",
    ),
    # 502 for the same reason the messaging provider gets one: this
    # application worked and the thing it depends on did not.
    EmbeddingProviderError: _Answer(
        status.HTTP_502_BAD_GATEWAY,
        "embedding_provider_error",
    ),
    ReplyProviderError: _Answer(
        status.HTTP_502_BAD_GATEWAY,
        "reply_provider_error",
    ),
    UnknownTimezoneError: _Answer(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "unknown_timezone",
    ),
    InvalidDateRangeError: _Answer(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_date_range",
    ),
}

_UNEXPECTED = _Answer(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error")


# Path parameters whose value is a credential rather than an identifier.
# An invitation token lives in the path, so a line logging the raw path
# would write a working invitation link into the log every time somebody
# followed one that had expired -- and a log is exactly where a secret
# gets copied, shipped, and kept longest.
_SECRET_PATH_PARAMS = frozenset({"token", "secret", "key", "password"})


def _loggable_path(request: Request) -> str:
    """The request path with any secret in it replaced by its name.

    `/api/v1/invitations/{token}`, but `/api/v1/workspaces/9f2c.../members/3`
    left exactly as it is. Only the parameters named above are hidden,
    because a workspace id in a log line is the thing that makes the line
    worth having, and blanket-redacting every parameter would throw that
    away to solve a problem only one of them has.
    """
    path = request.url.path

    for name, value in request.path_params.items():
        if name in _SECRET_PATH_PARAMS:
            path = path.replace(str(value), f"{{{name}}}")

    return path


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
        _loggable_path(request),
        exc,
    )

    # The answer's headers are the ones every instance of this error
    # carries; the exception's are the ones only this one knows, such as
    # how long a refused caller should wait.
    headers = {**(answer.headers or {}), **(exc.headers() or {})}

    return JSONResponse(
        status_code=answer.status_code,
        content=_body(answer.code, exc.detail),
        headers=headers or None,
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
        _loggable_path(request),
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
REFRESH_UNAUTHORISED = _documented(
    status.HTTP_401_UNAUTHORIZED,
    "The refresh token is unknown, spent, or its session has ended",
)
SESSION_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No live session of yours has that id",
)
BAD_LINK = _documented(
    status.HTTP_400_BAD_REQUEST,
    "This link is unknown, already used, or has expired",
)
RATE_LIMITED = _documented(
    status.HTTP_429_TOO_MANY_REQUESTS,
    "Too many requests. `Retry-After` says how many seconds to wait",
)
FORBIDDEN = _documented(status.HTTP_403_FORBIDDEN, "Inactive user")

# A route documents one description per status code, so where two errors
# share a code the description has to cover both rather than pick one.
WORKSPACE_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace, or you are not a member of it",
)
WORKSPACE_FORBIDDEN = _documented(
    status.HTTP_403_FORBIDDEN,
    "Inactive user, or your role does not permit this",
)
SLUG_CONFLICT = _documented(status.HTTP_409_CONFLICT, "Workspace slug already taken")
OWNERSHIP_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "You are still the only owner of a workspace",
)
MEMBER_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace, or that user is not a member of it",
)
MEMBER_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "A workspace must keep at least one owner",
)
INVITATION_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such invitation",
)
INVITATION_GONE = _documented(
    status.HTTP_410_GONE,
    "This invitation has expired",
)
INVITATION_FORBIDDEN = _documented(
    status.HTTP_403_FORBIDDEN,
    "Inactive user, or the invitation was sent to a different address",
)
INVITATION_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "Already a member, already invited, or already accepted",
)
CONTACT_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace or contact, or you are not a member",
)
CONTACT_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "A contact with that phone number already exists",
)
PRODUCT_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace or product, or you are not a member",
)
PRODUCT_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "That external id or SKU is already used in this workspace",
)
ORDER_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace, order or contact, or you are not a member",
)
ORDER_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "That external id is taken, or the order is not pending",
)
NOTIFICATION_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No notification of yours has that id",
)
AUTOMATION_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace or automation, or you are not a member",
)
AUTOMATION_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "That automation is already set up for this workspace",
)
BAD_AUTOMATION_SETTINGS = _documented(
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "Those settings are not valid for this automation",
)
STOREFRONT_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace, or no storefront is connected to it",
)
STOREFRONT_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "A storefront is already connected",
)
CONVERSATION_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace or conversation, or you are not a member",
)
CONVERSATION_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "That contact already has an open conversation, or this one is closed",
)
WHATSAPP_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace, or no WhatsApp account is connected to it",
)
WHATSAPP_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "A WhatsApp account is already connected",
)
KNOWLEDGE_NOT_FOUND = _documented(
    status.HTTP_404_NOT_FOUND,
    "No such workspace, source or document, or you are not a member",
)
KNOWLEDGE_CONFLICT = _documented(
    status.HTTP_409_CONFLICT,
    "This content is already in the knowledge base",
)
DOCUMENT_UNREADABLE = _documented(
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "No text could be read from this document",
)
DOCUMENT_UNSUPPORTED = _documented(
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "Only PDF and plain text files can be ingested",
)
EMBEDDING_UNAVAILABLE = _documented(
    status.HTTP_502_BAD_GATEWAY,
    "The embedding provider refused or could not be reached",
)
BAD_RANGE = _documented(
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "The date range is backwards, too long, or names an unknown timezone",
)
