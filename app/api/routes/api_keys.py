import uuid

from fastapi import APIRouter, status

from app.api.dependencies.api_key import AuthenticatedApiKeyDep
from app.api.dependencies.plan import REQUIRES_API_ACCESS
from app.api.dependencies.workspace import WorkspaceAdminDep
from app.api.errors import (
    API_KEY_NOT_FOUND,
    API_KEY_UNAUTHORISED,
    PLAN_REQUIRED,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyIdentity,
    ApiKeyRead,
)
from app.services.api_key_service import ApiKeyServiceDep

router = APIRouter(prefix="/workspaces/{workspace_id}/api-keys", tags=["api keys"])

# The endpoint a key authenticates rather than one a person does, so it
# hangs off no workspace: which workspace it addresses is the answer, not
# the question.
current_router = APIRouter(prefix="/api-keys", tags=["api keys"])

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


# Administration throughout. A key acts for the business without anybody
# watching, which is a decision about who may speak for it rather than
# something an agent adjusts between conversations.
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**SCOPED, **PLAN_REQUIRED},
    # Only creating is gated on the plan. A workspace that drops to one
    # without API access keeps being able to list and revoke what it
    # already issued -- being unable to turn off a credential because of
    # a billing change is the wrong way for anything to fail.
    dependencies=[REQUIRES_API_ACCESS],
)
def create_api_key(
    payload: ApiKeyCreate,
    access: WorkspaceAdminDep,
    service: ApiKeyServiceDep,
) -> ApiKeyCreated:
    """Issue a key, and return it once.

    The only response in this application that carries a credential the
    server cannot reproduce. A client that does not keep what comes back
    has to issue another key; there is no endpoint that will show it
    again, because nothing stored here could.
    """
    issued = service.create(access, payload)

    return ApiKeyCreated(
        **ApiKeyRead.model_validate(issued.key).model_dump(),
        key=issued.secret,
    )


@router.get("", responses=SCOPED)
def list_api_keys(
    access: WorkspaceAdminDep,
    service: ApiKeyServiceDep,
) -> list[ApiKeyRead]:
    """Every key this workspace has issued, revoked ones included.

    Revoked keys stay in the list because they are the useful half of the
    screen after an incident: which key it was, when it was last used, and
    when somebody turned it off.
    """
    return [ApiKeyRead.model_validate(key) for key in service.list_for(access)]


@router.delete(
    "/{key_id}",
    responses={**SCOPED, **API_KEY_NOT_FOUND},
)
def revoke_api_key(
    key_id: uuid.UUID,
    access: WorkspaceAdminDep,
    service: ApiKeyServiceDep,
) -> ApiKeyRead:
    """Stop a key working.

    Answers with the key rather than 204, and the row rather than nothing,
    because `revoked_at` is what somebody wants to see: the difference
    between having turned it off just now and finding a colleague already
    had.
    """
    return ApiKeyRead.model_validate(service.revoke(access, key_id))


@current_router.get("/current", responses=API_KEY_UNAUTHORISED)
def read_current_api_key(key: AuthenticatedApiKeyDep) -> ApiKeyIdentity:
    """What the key you are holding is, and which workspace it addresses.

    The call an integration makes first. It turns "the key is wrong" and
    "the key is right but points at the other business" into a failure at
    setup, rather than into messages arriving in somebody else's inbox a
    fortnight later.
    """
    return ApiKeyIdentity(
        workspace_id=key.workspace_id,
        name=key.name,
        key_prefix=key.key_prefix,
        expires_at=key.expires_at,
    )
