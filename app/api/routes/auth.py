from fastapi import APIRouter, Request, status

from app.api.dependencies.auth import CurrentUserDep
from app.api.errors import CONFLICT, FORBIDDEN, REFRESH_UNAUTHORISED, UNAUTHORISED
from app.schemas.auth import LoginRequest, RefreshTokenRequest, TokenPair
from app.schemas.user import UserCreate, UserRead
from app.services.auth_service import AuthServiceDep

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


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
    responses=CONFLICT,
)
def register(
    payload: UserCreate,
    service: AuthServiceDep,
) -> UserRead:
    return UserRead.model_validate(service.register(payload))


@router.post("/login", responses={**UNAUTHORISED, **FORBIDDEN})
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


@router.post("/refresh", responses={**REFRESH_UNAUTHORISED, **FORBIDDEN})
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
