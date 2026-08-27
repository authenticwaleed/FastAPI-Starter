"""Running the assistant after the webhook has already answered.

A customer's message arrives on a webhook, and Meta wants a prompt 200 --
anything slower is a delivery it sends again. Drafting a reply takes a
retrieval and a language model, which is seconds. So the two cannot happen
in the same breath: the delivery is recorded and acknowledged, and the
assistant runs afterwards.

The awkward part, and the reason this is its own module, is the session. A
FastAPI dependency that yields is torn down before the response is sent,
so a background task holding the request's session would be holding a
closed one. This opens its own, and takes the providers as arguments
rather than constructing them -- which is what keeps a test's fakes in
force for work that outlives the request that scheduled it.
"""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.integrations.embeddings.base import EmbeddingProvider
from app.integrations.llm.base import ReplyWriter
from app.integrations.messaging.base import MessagingProvider
from app.repositories.ai_response_log_repository import AiResponseLogRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_event_repository import (
    ConversationEventRepository,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.ai_response_service import AiResponseService
from app.services.message_service import MessageService
from app.services.retrieval_service import RetrievalService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

# Where a background run gets its session. A callable rather than the
# factory itself, because the thing that has to be substitutable is the
# whole "open one, close it afterwards" -- a test hands over the session
# its own transaction is already inside and keeps it open, which is what
# lets work scheduled by a request be rolled back with the request.
SessionSource = Callable[[], AbstractContextManager[Session]]


def open_session() -> AbstractContextManager[Session]:
    """A session of this run's own, closed when the run ends."""
    return get_session_factory()()


def get_session_source() -> SessionSource:
    return open_session


SessionSourceDep = Annotated[SessionSource, Depends(get_session_source)]


def build_ai_response_service(
    session: Session,
    *,
    embeddings: EmbeddingProvider,
    writer: ReplyWriter,
    messaging: MessagingProvider,
) -> AiResponseService:
    """Assemble the pipeline against one session.

    The same graph FastAPI builds from dependencies, written out once so a
    background run and a request produce the same object rather than two
    that have drifted.
    """
    conversations = ConversationRepository(session)
    messages = MessageRepository(session)
    accounts = WhatsAppAccountRepository(session)
    knowledge = KnowledgeRepository(session)

    return AiResponseService(
        session=session,
        conversations=conversations,
        messages=messages,
        logs=AiResponseLogRepository(session),
        retrieval=RetrievalService(knowledge=knowledge, embeddings=embeddings),
        writer=writer,
        events=ConversationEventRepository(session),
        outbound=MessageService(
            session=session,
            messages=messages,
            conversations=conversations,
            contacts=ContactRepository(session),
            accounts=accounts,
            whatsapp=WhatsAppService(
                session=session,
                accounts=accounts,
                provider=messaging,
            ),
        ),
    )


def answer_inbound(
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    embeddings: EmbeddingProvider,
    writer: ReplyWriter,
    messaging: MessagingProvider,
    session_source: SessionSource = open_session,
) -> None:
    """Have the assistant look at one customer message.

    Swallows everything. This runs after a 200 has already gone back to
    the provider, so there is nobody left to tell: an exception escaping
    here would be logged by the server as an unhandled error in a request
    that succeeded, and would tell the provider nothing either way. The
    customer's message is safely recorded whatever happens in here, which
    is the property that makes swallowing acceptable rather than lazy.
    """
    try:
        with session_source() as session:
            workspace = WorkspaceRepository(session).get(workspace_id)

            if workspace is None:
                logger.warning("A background reply named a workspace that is gone")
                return

            service = build_ai_response_service(
                session,
                embeddings=embeddings,
                writer=writer,
                messaging=messaging,
            )
            reply = service.generate_reply(
                workspace,
                conversation_id,
                incoming_message_id=message_id,
            )

            logger.info(
                "The assistant decided %s for conversation %s",
                reply.decision.value,
                conversation_id,
            )
    except Exception:
        logger.exception(
            "A background reply failed for conversation %s",
            conversation_id,
        )
