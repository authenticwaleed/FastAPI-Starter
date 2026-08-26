import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.workspace import WorkspaceAgentDep, WorkspaceMemberDep
from app.api.errors import (
    CONTACT_NOT_FOUND,
    CONVERSATION_CONFLICT,
    CONVERSATION_NOT_FOUND,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.conversation import ConversationStatus
from app.schemas.conversation import (
    ConversationAssign,
    ConversationCreate,
    ConversationPage,
    ConversationRead,
    ConversationUpdate,
)
from app.schemas.message import MessageCreate, MessagePage, MessageRead
from app.services.conversation_service import ConversationServiceDep
from app.services.message_service import MessageServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/conversations",
    tags=["conversations"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}
NAMED = {**SCOPED, **CONVERSATION_NOT_FOUND}


# Reading takes WorkspaceMemberDep and everything else takes
# WorkspaceAgentDep: the plan gives an agent "view conversations, send
# messages, take over conversations", which is this list, and leaves a
# viewer with the dashboard and nothing to press.
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**SCOPED, **CONTACT_NOT_FOUND, **CONVERSATION_CONFLICT},
)
def open_conversation(
    payload: ConversationCreate,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    return ConversationRead.model_validate(service.create(access, payload))


@router.get("", responses=SCOPED)
def list_conversations(
    access: WorkspaceMemberDep,
    service: ConversationServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[ConversationStatus | None, Query(alias="status")] = None,
    assigned_to: Annotated[int | None, Query()] = None,
    unassigned: Annotated[bool, Query()] = False,
    contact_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ConversationPage:
    """The inbox: most recently active first.

    `unassigned=true` wins over `assigned_to`, because asking for both is
    a contradiction and the one with no answer should not silently become
    the one with an answer.
    """
    conversations, total = service.list_for(
        access,
        page=page,
        page_size=page_size,
        status=status_filter,
        assigned_user_id=assigned_to,
        contact_id=contact_id,
        unassigned=unassigned,
    )

    return ConversationPage(
        items=[
            ConversationRead.model_validate(conversation)
            for conversation in conversations
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{conversation_id}", responses=NAMED)
def read_conversation(
    conversation_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    return ConversationRead.model_validate(service.get(access, conversation_id))


@router.patch(
    "/{conversation_id}",
    responses={**NAMED, **CONVERSATION_CONFLICT},
)
def update_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    return ConversationRead.model_validate(
        service.update(access, conversation_id, payload)
    )


@router.post("/{conversation_id}/assign", responses=NAMED)
def assign_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationAssign,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    """Hand the thread to a colleague, or send `null` to unassign it."""
    return ConversationRead.model_validate(
        service.assign(access, conversation_id, payload.user_id)
    )


@router.post("/{conversation_id}/close", responses=NAMED)
def close_conversation(
    conversation_id: uuid.UUID,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    """Closing an already closed conversation changes nothing and says so
    with the same 200, so a double click is not an error."""
    return ConversationRead.model_validate(service.close(access, conversation_id))


@router.post(
    "/{conversation_id}/reopen",
    responses={**NAMED, **CONVERSATION_CONFLICT},
)
def reopen_conversation(
    conversation_id: uuid.UUID,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    return ConversationRead.model_validate(service.reopen(access, conversation_id))


@router.get("/{conversation_id}/messages", responses=NAMED)
def list_messages(
    conversation_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: MessageServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
) -> MessagePage:
    messages, total = service.list_for(
        access,
        conversation_id,
        page=page,
        page_size=page_size,
    )

    return MessagePage(
        items=[MessageRead.model_validate(message) for message in messages],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{conversation_id}/messages",
    status_code=status.HTTP_201_CREATED,
    responses={**NAMED, **CONVERSATION_CONFLICT},
)
def send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    access: WorkspaceAgentDep,
    service: MessageServiceDep,
) -> MessageRead:
    """Reply to the customer.

    The message is stored `queued` and stays there: nothing delivers it
    yet. Connecting a provider is the next phase, and that is what will
    move it to sent and then delivered.
    """
    return MessageRead.model_validate(service.send(access, conversation_id, payload))
