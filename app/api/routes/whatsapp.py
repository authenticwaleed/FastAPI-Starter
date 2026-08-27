from fastapi import APIRouter, status

from app.api.dependencies.workspace import WorkspaceAdminDep, WorkspaceMemberDep
from app.api.errors import (
    UNAUTHORISED,
    WHATSAPP_CONFLICT,
    WHATSAPP_NOT_FOUND,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.schemas.whatsapp import WhatsAppAccountRead, WhatsAppConnect
from app.services.whatsapp_service import WhatsAppServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/integrations/whatsapp",
    tags=["whatsapp"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


# Connecting and disconnecting take WorkspaceAdminDep: the plan gives an
# admin "manage integrations", and handing over a provider credential is
# not something an agent does in the course of answering customers.
@router.post(
    "/connect",
    status_code=status.HTTP_201_CREATED,
    responses={**SCOPED, **WHATSAPP_CONFLICT},
)
def connect_whatsapp(
    payload: WhatsAppConnect,
    access: WorkspaceAdminDep,
    service: WhatsAppServiceDep,
) -> WhatsAppAccountRead:
    """Connect the workspace's WhatsApp Business number.

    The access token is encrypted before it is stored and does not appear
    in the response, in any later response, or in any log line.
    """
    return WhatsAppAccountRead.model_validate(service.connect(access, payload))


@router.get("", responses={**SCOPED, **WHATSAPP_NOT_FOUND})
def read_whatsapp(
    access: WorkspaceMemberDep,
    service: WhatsAppServiceDep,
) -> WhatsAppAccountRead:
    """What is connected. Readable by any member; the token is not here."""
    return WhatsAppAccountRead.model_validate(service.get(access))


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**SCOPED, **WHATSAPP_NOT_FOUND},
)
def disconnect_whatsapp(
    access: WorkspaceAdminDep,
    service: WhatsAppServiceDep,
) -> None:
    """Disconnect the number, deleting the stored credential with it."""
    service.disconnect(access)
