"""Running automations after the response that caused them has gone.

Same reason ai_dispatch exists, and the same shape. What an automation
does is message a customer, and a provider taking four seconds must not
be four seconds a webhook spends before acknowledging -- or four seconds
a shopkeeper waits for an order form to submit.

The session is the awkward part, and is why this is a module rather than
a method. A FastAPI dependency that yields is torn down before the
response is sent, so a background task holding the request's session
would be holding a closed one. This opens its own, and takes the
messaging provider as an argument rather than constructing it -- which is
what keeps a test's fakes in force for work that outlives the request
that scheduled it.
"""

import logging
import uuid

from sqlalchemy.orm import Session

from app.integrations.messaging.base import MessagingProvider
from app.models.automation import AutomationTrigger
from app.repositories.automation_repository import AutomationRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_event_repository import (
    ConversationEventRepository,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.ai_dispatch import (
    SessionSource,
    build_usage_service,
    open_session,
)
from app.services.automation_service import AutomationService
from app.services.automations import Tools, Trigger
from app.services.message_service import MessageService
from app.services.notification_service import NotificationService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


def build_automation_service(
    session: Session,
    *,
    messaging: MessagingProvider,
) -> AutomationService:
    """Assemble the engine against one session.

    The same graph FastAPI builds from dependencies, written out once so
    a background run and a request produce the same object rather than
    two that have drifted.
    """
    conversations = ConversationRepository(session)
    messages = MessageRepository(session)
    accounts = WhatsAppAccountRepository(session)
    contacts = ContactRepository(session)
    automations = AutomationRepository(session)
    notifications = NotificationService(
        session=session,
        notifications=NotificationRepository(session),
        memberships=WorkspaceMembershipRepository(session),
    )

    return AutomationService(
        session=session,
        automations=automations,
        tools=Tools(
            session=session,
            messages=MessageService(
                session=session,
                messages=messages,
                conversations=conversations,
                contacts=contacts,
                accounts=accounts,
                whatsapp=WhatsAppService(
                    session=session,
                    accounts=accounts,
                    provider=messaging,
                ),
                notifications=notifications,
                usage=build_usage_service(session),
            ),
            message_repository=messages,
            conversations=conversations,
            events=ConversationEventRepository(session),
            contacts=contacts,
            orders=OrderRepository(session),
            automations=automations,
        ),
    )


def fire_automations(
    *,
    workspace_id: uuid.UUID,
    trigger_type: AutomationTrigger,
    messaging: MessagingProvider,
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    session_source: SessionSource = open_session,
) -> None:
    """Consider every enabled automation for what just happened.

    Swallows everything, for the reason answer_inbound does: this runs
    after a response has already gone, so there is nobody left to tell,
    and an exception escaping here would be logged by the server as an
    unhandled error in a request that succeeded. What actually happened
    is in automation_runs either way, which is the property that makes
    swallowing acceptable rather than lazy.
    """
    try:
        with session_source() as session:
            workspace = WorkspaceRepository(session).get(workspace_id)

            if workspace is None:
                logger.warning("An automation named a workspace that is gone")
                return

            service = build_automation_service(session, messaging=messaging)
            runs = service.fire(
                workspace,
                Trigger(
                    type=trigger_type,
                    workspace=workspace,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    order_id=order_id,
                ),
            )

            logger.info(
                "%s automation(s) considered %s",
                len(runs),
                trigger_type.value,
            )
    except Exception:
        logger.exception("Automations failed for %s", trigger_type.value)
