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

from app.core import context
from app.core.exceptions import RateLimitExceededError
from app.core.rate_limit import RateLimited, RateLimiter
from app.db.session import get_session_factory
from app.integrations.embeddings.base import EmbeddingProvider
from app.integrations.llm.base import ReplyWriter
from app.integrations.messaging.base import MessagingProvider
from app.models.workspace import WorkspaceStatus
from app.repositories.ai_response_log_repository import AiResponseLogRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_event_repository import (
    ConversationEventRepository,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.job_repository import JobRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.plan_override_repository import PlanOverrideRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.usage_repository import UsageRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.ai_response_service import AiResponseService
from app.services.audit_service import AuditService
from app.services.commerce_context import CommerceContextService
from app.services.message_service import MessageService
from app.services.notification_service import NotificationService
from app.services.retrieval_service import RetrievalService
from app.services.subscription_service import (
    SubscriptionService,
    get_billing_provider,
)
from app.services.usage_service import UsageService
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


def build_audit_service(session: Session) -> AuditService:
    """The audit log, assembled against one session.

    Wanted here because the graphs below reach services that record
    administrative acts. Nothing a background run does is itself an
    audited act -- answering a customer is the work, not administration --
    but the services it borrows write entries when a person uses them.
    """
    return AuditService(session=session, logs=AuditLogRepository(session))


def build_usage_service(session: Session) -> UsageService:
    """The meter, assembled against one session.

    Wanted by every background graph, because the work they do is
    precisely the work that costs something: a webhook that answered a
    customer without metering it would be usage nothing charged for.
    """
    return UsageService(usage=UsageRepository(session))


def build_subscription_service(session: Session) -> SubscriptionService:
    """The capability checks, assembled against one session.

    Wanted by the background graphs because the assistant's quota is
    checked before it drafts, and a run that skipped the check would let
    a webhook spend what a dashboard could not.
    """
    return SubscriptionService(
        session=session,
        subscriptions=SubscriptionRepository(session),
        overrides=PlanOverrideRepository(session),
        provider=get_billing_provider(),
        notifications=NotificationService(
            session=session,
            notifications=NotificationRepository(session),
            memberships=WorkspaceMembershipRepository(session),
        ),
        usage=build_usage_service(session),
        audit=build_audit_service(session),
    )


def build_message_service(
    session: Session,
    *,
    messaging: MessagingProvider,
) -> MessageService:
    """Sending, assembled against one session.

    Written out once because three graphs want it: the assistant
    answering a webhook, an automation messaging a customer, and the
    worker retrying a delivery that did not go. Three copies of a
    constructor is three places to edit the next time it grows an
    argument, and the last time it did the third was the one that would
    have been missed.
    """
    accounts = WhatsAppAccountRepository(session)
    conversations = ConversationRepository(session)

    return MessageService(
        session=session,
        messages=MessageRepository(session),
        conversations=conversations,
        contacts=ContactRepository(session),
        accounts=accounts,
        whatsapp=WhatsAppService(
            session=session,
            accounts=accounts,
            provider=messaging,
            audit=build_audit_service(session),
        ),
        notifications=NotificationService(
            session=session,
            notifications=NotificationRepository(session),
            memberships=WorkspaceMembershipRepository(session),
        ),
        usage=build_usage_service(session),
        jobs=JobRepository(session),
    )


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
    knowledge = KnowledgeRepository(session)
    notifications = NotificationService(
        session=session,
        notifications=NotificationRepository(session),
        memberships=WorkspaceMembershipRepository(session),
    )
    usage = build_usage_service(session)

    return AiResponseService(
        session=session,
        conversations=conversations,
        messages=messages,
        logs=AiResponseLogRepository(session),
        retrieval=RetrievalService(knowledge=knowledge, embeddings=embeddings),
        commerce=CommerceContextService(
            products=ProductRepository(session),
            orders=OrderRepository(session),
        ),
        writer=writer,
        events=ConversationEventRepository(session),
        notifications=notifications,
        subscriptions=build_subscription_service(session),
        usage=usage,
        outbound=build_message_service(session, messaging=messaging),
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
    limiter: RateLimiter | None = None,
) -> None:
    """Have the assistant look at one customer message.

    Swallows everything. This runs after a 200 has already gone back to
    the provider, so there is nobody left to tell: an exception escaping
    here would be logged by the server as an unhandled error in a request
    that succeeded, and would tell the provider nothing either way. The
    customer's message is safely recorded whatever happens in here, which
    is the property that makes swallowing acceptable rather than lazy.

    `limiter` bounds what a workspace can spend on a language model, from
    the same counters the dashboard's AI endpoint spends from. It is the
    only limit in this application that stops a customer being answered,
    and it is set high enough that reaching it means something is wrong
    rather than busy -- two bots talking to each other is the case it
    exists for. When it trips, the message is already stored and shows up
    unanswered in the inbox, which is what a person is for.
    """
    # Bound for the whole run, so every line the assistant writes says
    # which business and which thread it was about. The request id is
    # already there and is not rebound: this work was scheduled by a
    # webhook and inherits its context, which is what lets one search turn
    # up the delivery, the reply it produced, and the model call it cost.
    with context.bound(workspace_id=workspace_id, conversation_id=conversation_id):
        _answer(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=message_id,
            embeddings=embeddings,
            writer=writer,
            messaging=messaging,
            session_source=session_source,
            limiter=limiter,
        )


def _answer(
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    embeddings: EmbeddingProvider,
    writer: ReplyWriter,
    messaging: MessagingProvider,
    session_source: SessionSource,
    limiter: RateLimiter | None,
) -> None:
    try:
        if limiter is not None:
            limiter.spend(RateLimited.AI, str(workspace_id))

        with session_source() as session:
            workspace = WorkspaceRepository(session).get(workspace_id)

            if workspace is None:
                logger.warning("A background reply named a workspace that is gone")
                return

            if workspace.status == WorkspaceStatus.SUSPENDED:
                # The other half of what a suspension means, and the one
                # the plan asks to be decided explicitly: accept and
                # store, do not auto-reply.
                #
                # The message is already recorded by the time this runs.
                # Refusing to ingest it would lose a customer's question
                # over their supplier's unpaid invoice, which is the
                # worst thing a suspension could do to somebody who is
                # not party to it. Answering on the business's behalf
                # while its account is frozen would be the second worst.
                #
                # So it sits unanswered in an inbox the business can
                # still read, which is exactly where a person would find
                # it.
                logger.info(
                    "Workspace %s is suspended; conversation %s is left for a person",
                    workspace_id,
                    conversation_id,
                )
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
    except RateLimitExceededError:
        logger.warning(
            "Workspace %s is over its assistant limit; conversation %s is "
            "left for a person",
            workspace_id,
            conversation_id,
        )
    except Exception:
        logger.exception(
            "A background reply failed for conversation %s",
            conversation_id,
        )
