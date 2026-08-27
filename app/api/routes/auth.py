from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from app.api.dependencies.auth import CurrentUserDep
from app.api.dependencies.rate_limit import limit_by_client
from app.api.errors import (
    BAD_LINK,
    CONFLICT,
    FORBIDDEN,
    RATE_LIMITED,
    REFRESH_UNAUTHORISED,
    UNAUTHORISED,
)
from app.core.rate_limit import RateLimited
from app.schemas.auth import (
    EmailRequest,
    LoginRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    TokenPair,
    VerifyEmailRequest,
)
from app.schemas.user import UserCreate, UserRead
from app.services.ai_dispatch import SessionSourceDep
from app.services.auth_service import AuthServiceDep
from app.services.email_dispatch import (
    EmailSenderDep,
    send_password_reset_email,
    send_verification_email,
)
from app.services.verification_service import VerificationServiceDep

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

# Two buckets, both keyed on the caller's address because none of these
# endpoints has an account to key on yet.
#
# AUTH covers presenting a credential: a password at /login, a refresh
# token at /refresh. Both are worth guessing at, and neither is worth
# guessing at ten times a minute.
#
# EMAIL covers the three endpoints that will send mail to an address the
# caller chose. That is an unauthenticated way to make this service email
# a stranger, so it is the tightest limit here by some distance.
BY_ADDRESS = Depends(limit_by_client(RateLimited.AUTH))
BY_ADDRESS_FOR_EMAIL = Depends(limit_by_client(RateLimited.EMAIL))


def _who_is_asking(request: Request) -> tuple[str | None, str | None]:
    """The two labels a session list shows, taken from the request.

    Both are best effort and neither decides anything: `User-Agent` is
    whatever the client chose to send, and the address is the peer's,
    which is the proxy's unless uvicorn is running with `--proxy-headers`.
    They exist so that somebody scanning their own sessions can tell which
    row is the laptop they left at the office.
    """
    return (
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
    )


# Sync for the same reason as the user routes: the session is blocking, so
# an async handler would stall the event loop while a query runs.
@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={**CONFLICT, **RATE_LIMITED},
    dependencies=[BY_ADDRESS_FOR_EMAIL],
)
def register(
    payload: UserCreate,
    background: BackgroundTasks,
    service: AuthServiceDep,
    sender: EmailSenderDep,
    session_source: SessionSourceDep,
) -> UserRead:
    """Create the account, and ask the address to confirm itself.

    The email is scheduled rather than sent here: a mail server that is
    slow, or down, must not be able to fail a registration that has
    already succeeded. Nothing is gated on confirming, so an account that
    never receives the message still works.
    """
    user = service.register(payload)

    background.add_task(
        send_verification_email,
        email=user.email,
        # Handed over rather than rebuilt, so a test's fake stays in force
        # for work that outlives the request that scheduled it.
        sender=sender,
        session_source=session_source,
    )

    return UserRead.model_validate(user)


@router.post(
    "/login",
    responses={**UNAUTHORISED, **FORBIDDEN, **RATE_LIMITED},
    dependencies=[BY_ADDRESS],
)
def login(
    credentials: LoginRequest,
    request: Request,
    service: AuthServiceDep,
) -> TokenPair:
    user_agent, ip_address = _who_is_asking(request)

    return service.login(
        credentials,
        user_agent=user_agent,
        ip_address=ip_address,
    )


@router.post(
    "/refresh",
    responses={**REFRESH_UNAUTHORISED, **FORBIDDEN, **RATE_LIMITED},
    dependencies=[BY_ADDRESS],
)
def refresh(
    payload: RefreshTokenRequest,
    service: AuthServiceDep,
) -> TokenPair:
    """Exchange the refresh token for a new pair.

    Unauthenticated, and deliberately so: the whole reason to call this
    is that the access token has run out, and requiring a live one would
    make the endpoint useless at the only moment it is needed. The
    refresh token is the credential.

    Both tokens in the response are new. The one that was sent is spent,
    and sending it a second time ends the session -- see
    `RefreshTokenReusedError`.
    """
    return service.refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: RefreshTokenRequest,
    service: AuthServiceDep,
) -> None:
    """End the session the refresh token belongs to.

    Unauthenticated for the same reason as refresh, and always 204: a
    client that has lost track of what it holds should still be able to
    say "forget this", and an answer that varied would tell whoever is
    guessing which tokens are real.
    """
    service.logout(payload.refresh_token)


@router.get("/me", responses={**UNAUTHORISED, **FORBIDDEN})
def read_current_user(user: CurrentUserDep) -> UserRead:
    """The protected endpoint. The dependency has already done the work."""
    return UserRead.model_validate(user)


# --- confirming an address, and getting back in ---------------------------
#
# The first two of these take an email address and answer 202 whatever it
# is. Nothing about the response -- body, status, or how long it took --
# differs between an address with an account behind it and one without,
# which is the point: an endpoint anybody can call that answered
# differently for real addresses would be a way of asking who has an
# account here. The work happens in the background for the same reason,
# and there is more about that in email_dispatch.


@router.post(
    "/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    responses=RATE_LIMITED,
    dependencies=[BY_ADDRESS_FOR_EMAIL],
)
def resend_verification(
    payload: EmailRequest,
    background: BackgroundTasks,
    sender: EmailSenderDep,
    session_source: SessionSourceDep,
) -> None:
    """Send another confirmation link, if there is one to send.

    Also the way back after changing an address: doing that clears the
    confirmation, because what was confirmed was the old one.
    """
    background.add_task(
        send_verification_email,
        email=payload.email,
        sender=sender,
        session_source=session_source,
    )


@router.post(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=BAD_LINK,
)
def verify_email(
    payload: VerifyEmailRequest,
    service: VerificationServiceDep,
) -> None:
    """Confirm the address the link was sent to.

    Nothing is returned, and nothing is signed in. Somebody arriving here
    came from a mailbox rather than from a session, and handing out a
    token to whoever followed a link would make the link a login.
    """
    service.verify_email(payload.token)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    responses=RATE_LIMITED,
    dependencies=[BY_ADDRESS_FOR_EMAIL],
)
def forgot_password(
    payload: EmailRequest,
    background: BackgroundTasks,
    sender: EmailSenderDep,
    session_source: SessionSourceDep,
) -> None:
    """Send a reset link, if this address has an account to reset."""
    background.add_task(
        send_password_reset_email,
        email=payload.email,
        sender=sender,
        session_source=session_source,
    )


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=BAD_LINK,
)
def reset_password(
    payload: ResetPasswordRequest,
    service: VerificationServiceDep,
) -> None:
    """Replace the password, and sign every session out.

    No token comes back here either. Somebody who has just reset a
    password should be made to use it, which is also what proves the
    reset did what they think it did.
    """
    service.reset_password(payload.token, payload.new_password)
