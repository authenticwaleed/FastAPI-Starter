import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.rate_limit import limit_by_workspace
from app.api.dependencies.workspace import WorkspaceAgentDep, WorkspaceMemberDep
from app.api.errors import (
    CONVERSATION_NOT_FOUND,
    RATE_LIMITED,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.core.rate_limit import RateLimited
from app.schemas.ai import (
    AiReplyRead,
    AiResponseLogPage,
    AiResponseLogRead,
)
from app.services.ai_response_service import (
    AiResponseLogRepositoryDep,
    AiResponseServiceDep,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/conversations/{conversation_id}",
    tags=["ai"],
)

NAMED = {
    **UNAUTHORISED,
    **WORKSPACE_FORBIDDEN,
    **WORKSPACE_NOT_FOUND,
    **CONVERSATION_NOT_FOUND,
}


# Per workspace, and the same bucket the assistant spends from when it
# answers a webhook by itself -- see ai_dispatch. A business's spend on a
# language model is one number whether the reply was asked for from the
# dashboard or triggered by a customer.
@router.post(
    "/ai-reply",
    responses={**NAMED, **RATE_LIMITED},
    dependencies=[Depends(limit_by_workspace(RateLimited.AI))],
)
def generate_ai_reply(
    conversation_id: uuid.UUID,
    access: WorkspaceAgentDep,
    service: AiResponseServiceDep,
) -> AiReplyRead:
    """Have the assistant draft a reply to the customer's last message.

    Answers 200 whatever it decides, including when it decides not to
    answer. A handoff, an empty knowledge base and a model that is down
    are outcomes rather than errors, and a client needs to tell them
    apart -- which it cannot do from a status code. Branch on `decision`.

    Calling it twice runs it twice, deliberately: the reason to press this
    is that something has changed -- the assistant was switched off, the
    model was down, the knowledge base has since been filled in. The one
    thing it will not do is send a second reply to a message that was
    already answered; that call replays the answer, message id included.

    Whether the reply is sent or only drafted is the conversation's
    `ai_mode` and not this endpoint's to decide: `automatic` sends,
    `suggest_only` returns the draft for a human, `disabled` refuses. That
    is what makes the plan's pilots safe -- the mode is set once on the
    conversation and every path through the assistant obeys it.
    """
    reply = service.generate_reply(
        access.workspace,
        conversation_id,
        requested_by_human=True,
    )

    return AiReplyRead(
        decision=reply.decision,
        text=reply.text,
        confidence=reply.confidence,
        reason=reply.reason,
        sources=reply.sources,
        message_id=reply.message_id,
    )


@router.get("/ai-responses", responses=NAMED)
def list_ai_responses(
    conversation_id: uuid.UUID,
    access: WorkspaceMemberDep,
    logs: AiResponseLogRepositoryDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AiResponseLogPage:
    """What the assistant decided on this thread, and why.

    Most recent first. The rows where it decided *not* to answer are the
    ones worth reading: they carry the reason, the score of the evidence
    it found, and the version of the prompt that judged it.
    """
    workspace_id = access.workspace.id
    items = logs.list_for_conversation(
        workspace_id,
        conversation_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )

    return AiResponseLogPage(
        items=[AiResponseLogRead.model_validate(item) for item in items],
        total=logs.count_for_conversation(workspace_id, conversation_id),
        page=page,
        page_size=page_size,
    )
