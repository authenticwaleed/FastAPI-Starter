"""Authenticating software rather than a person.

A second way in, deliberately separate from the first. A person arrives
with a bearer token naming a session that can be ended; a customer's
integration arrives with a key naming a workspace, and has no session, no
membership and nobody to prompt for a password.

Keeping them apart is what stops either from quietly becoming the other.
The key travels in a header of its own rather than in `Authorization`, so
a request carrying both is unambiguous and a client that sends the wrong
one is told which scheme it should have used.
"""

from typing import Annotated

from fastapi import Depends, Header

from app.models.api_key import ApiKey
from app.services.api_key_service import ApiKeyServiceDep

# The header a key travels in. Named once so the route, its documentation
# and any client this project ever writes cannot disagree about it.
API_KEY_HEADER = "X-API-Key"


def get_authenticated_api_key(
    service: ApiKeyServiceDep,
    x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None,
) -> ApiKey:
    """The key behind this request, or 401.

    A missing header and an invalid key are the same refusal, which is the
    same choice the service makes for revoked and expired: none of the
    distinctions help a legitimate caller, and each of them tells somebody
    holding a string they found something about what it is.
    """
    return service.authenticate(x_api_key or "")


AuthenticatedApiKeyDep = Annotated[ApiKey, Depends(get_authenticated_api_key)]
