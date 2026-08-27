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
from app.repositories.conversation_repository import InboxRow
from app.schemas.conversation import (
    AssigneeSummary,
    ContactSummary,
    ConversationAssign,
    ConversationCreate,
    ConversationEventPage,
    ConversationEventRead,
    ConversationPage,
    ConversationRead,
    ConversationRelease,
    ConversationTakeover,
    ConversationUpdate,
    MessagePreview,
)
from app.schemas.message import MessageCreate, MessagePage, MessageRead
from app.services.conversation_service import ConversationServiceDep
from app.services.message_service import MessageServiceDep
from app.services.workspace_service import WorkspaceAccess

router = APIRouter(
    prefix="/workspaces/{workspace_id}/conversations",
    tags=["conversations"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}
NAMED = {**SCOPED, **CONVERSATION_NOT_FOUND}

# `me` rather than a user id the client has to look up first. Every inbox
# opens on "mine", and requiring the caller to know its own numeric id to
# ask for it is a lookup that exists only because the API would not accept
# the word.
ASSIGNED_TO = r"^(me|[0-9]+)$"


def _read(row: InboxRow) -> ConversationRead:
    """One conversation, with what it takes to render it, as one object."""
    return ConversationRead(
        id=row.conversation.id,
        contact=ContactSummary.model_validate(row.contact),
        channel=row.conversation.channel,
        status=row.conversation.status,
        assigned_user=(
            None
            if row.assignee is None
            else AssigneeSummary.model_validate(row.assignee)
        ),
        ai_mode=row.conversation.ai_mode,
        state=row.conversation.state,
        handoff_at=row.conversation.handoff_at,
        handoff_reason=row.conversation.handoff_reason,
        handoff_by_user_id=row.conversation.handoff_by_user_id,
        last_message=(
            None
            if row.last_message is None
            else MessagePreview.model_validate(row.last_message)
        ),
        last_message_at=row.conversation.last_message_at,
        unread_count=row.conversation.unread_count,
        last_read_at=row.conversation.last_read_at,
        opened_at=row.conversation.opened_at,
        closed_at=row.conversation.closed_at,
        created_at=row.conversation.created_at,
        updated_at=row.conversation.updated_at,
    )


def _assignee(access: WorkspaceAccess, assigned_to: str | None) -> int | None:
    """Resolve the `assigned_to` filter to a user id, `me` included."""
    if assigned_to is None:
        return None

    if assigned_to == "me":
        return access.membership.user_id

    return int(assigned_to)


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
    return _read(service.create(access, payload))


@router.get("", responses=SCOPED)
def list_conversations(
    access: WorkspaceMemberDep,
    service: ConversationServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
    status_filter: Annotated[
        list[ConversationStatus] | None,
        Query(alias="status"),
    ] = None,
    assigned_to: Annotated[str | None, Query(pattern=ASSIGNED_TO)] = None,
    unassigned: Annotated[bool, Query()] = False,
    contact_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=150)] = None,
) -> ConversationPage:
    """The inbox: most recently active first.

    `status` may be repeated -- `?status=open&status=pending` is the view
    an inbox opens on, since a thread waiting on a delivery is still one
    somebody has to come back to.

    `assigned_to=me` is the caller, `assigned_to=<user id>` a colleague,
    and `search` matches the contact rather than the messages: whoever is
    looking has a person in mind, and searching what was said inside every
    thread is a different feature with a different index behind it.

    `unassigned=true` wins over `assigned_to`, because asking for both is
    a contradiction and the one with no answer should not silently become
    the one with an answer.
    """
    rows, total = service.list_for(
        access,
        page=page,
        page_size=page_size,
        statuses=status_filter,
        assigned_user_id=_assignee(access, assigned_to),
        contact_id=contact_id,
        unassigned=unassigned,
        search=search,
    )

    return ConversationPage(
        items=[_read(row) for row in rows],
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
    return _read(service.detail(access, conversation_id))


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
    return _read(service.update(access, conversation_id, payload))


@router.post("/{conversation_id}/assign", responses=NAMED)
def assign_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationAssign,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    """Hand the thread to a colleague, or send `null` to unassign it."""
    return _read(service.assign(access, conversation_id, payload.user_id))


@router.post("/{conversation_id}/read", responses=NAMED)
def mark_conversation_read(
    conversation_id: uuid.UUID,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    """Clear the unread count, for everyone.

    Takes an agent rather than any member for that reason: the count
    belongs to the team's queue, and somebody with read-only access to the
    dashboard should not be able to clear a badge their colleagues work
    from.
    """
    return _read(service.mark_read(access, conversation_id))


@router.post("/{conversation_id}/takeover", responses=NAMED)
def take_over_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationTakeover,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    """Take the thread over from the assistant.

    Switches the assistant off for this conversation and assigns it to
    you. It stays off until somebody releases it -- an assistant answering
    alongside an agent is two voices contradicting each other in front of
    a customer, and the plan makes stopping that a rule rather than a
    preference.
    """
    return _read(service.take_over(access, conversation_id, payload.reason))


@router.post("/{conversation_id}/release-to-ai", responses=NAMED)
def release_conversation_to_ai(
    conversation_id: uuid.UUID,
    payload: ConversationRelease,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    """Hand the thread back to the assistant.

    Back to drafting unless you say otherwise. The assignment is left
    alone: releasing the assistant and dropping the thread are two
    decisions, and whoever took it is usually still the right person to
    see the customer's reply.
    """
    return _read(service.release_to_ai(access, conversation_id, payload.ai_mode))


@router.get("/{conversation_id}/events", responses=NAMED)
def list_conversation_events(
    conversation_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: ConversationServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ConversationEventPage:
    """Who has had this thread, and why. Most recent first."""
    events, total = service.history(
        access,
        conversation_id,
        page=page,
        page_size=page_size,
    )

    return ConversationEventPage(
        items=[ConversationEventRead.model_validate(event) for event in events],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{conversation_id}/close", responses=NAMED)
def close_conversation(
    conversation_id: uuid.UUID,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    """Closing an already closed conversation changes nothing and says so
    with the same 200, so a double click is not an error."""
    return _read(service.close(access, conversation_id))


@router.post(
    "/{conversation_id}/reopen",
    responses={**NAMED, **CONVERSATION_CONFLICT},
)
def reopen_conversation(
    conversation_id: uuid.UUID,
    access: WorkspaceAgentDep,
    service: ConversationServiceDep,
) -> ConversationRead:
    return _read(service.reopen(access, conversation_id))


@router.get("/{conversation_id}/messages", responses=NAMED)
def list_messages(
    conversation_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: MessageServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
) -> MessagePage:
    messages, total = service.list_for(
        access.workspace,
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
    """Reply to the customer, and mark the thread read.

    Replying is the strongest statement there is that somebody has read a
    thread, and a shared inbox that still shows a badge on a conversation
    a colleague has just answered is one that gets answered twice.
    """
    return MessageRead.model_validate(
        service.send(access.workspace, conversation_id, payload)
    )
