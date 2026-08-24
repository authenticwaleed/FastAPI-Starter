from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import InvalidCredentialsError
from app.models.user import User
from app.services.auth_service import AuthServiceDep

# auto_error=False so a missing Authorization header reaches the code below.
# Left to itself HTTPBearer answers a missing header with 403, where an
# absent token is really "you have not authenticated yet", a 401.
bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]


def get_current_user(
    credentials: BearerCredentials,
    service: AuthServiceDep,
) -> User:
    """Resolve the bearer token into the user making the request.

    Endpoints depend on this rather than on a token, so a handler receives a
    User and never has to think about headers.
    """
    if credentials is None:
        raise InvalidCredentialsError(detail="Not authenticated")

    return service.current_user(credentials.credentials)


CurrentUserDep = Annotated[User, Depends(get_current_user)]
