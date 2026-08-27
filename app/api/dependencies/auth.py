from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import InvalidCredentialsError
from app.models.user import User
from app.models.user_session import UserSession
from app.services.auth_service import Authenticated, AuthServiceDep

# auto_error=False so a missing Authorization header reaches the code below.
# Left to itself HTTPBearer answers a missing header with 403, where an
# absent token is really "you have not authenticated yet", a 401.
bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]


def get_authenticated(
    credentials: BearerCredentials,
    service: AuthServiceDep,
) -> Authenticated:
    """Resolve the bearer token into the caller and the session behind it.

    The one place the token is read. The two dependencies below are views
    onto its result rather than second lookups: FastAPI resolves a
    dependency once per request, so a route asking for both gets one
    decode and one query.
    """
    if credentials is None:
        raise InvalidCredentialsError(detail="Not authenticated")

    return service.authenticate_token(credentials.credentials)


AuthenticatedDep = Annotated[Authenticated, Depends(get_authenticated)]


def get_current_user(authenticated: AuthenticatedDep) -> User:
    """The user making the request.

    Endpoints depend on this rather than on a token, so a handler receives a
    User and never has to think about headers.
    """
    return authenticated.user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_current_session(authenticated: AuthenticatedDep) -> UserSession:
    """The sign-in the request arrived on.

    Wanted by the handful of routes that manage sessions: which row to
    label "this device", and which one not to sign out when a password
    change signs out all the others.
    """
    return authenticated.session


CurrentSessionDep = Annotated[UserSession, Depends(get_current_session)]
