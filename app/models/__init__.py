"""Model package.

Importing this package registers every table on `Base.metadata`, which is
what Alembic autogenerate needs in order to see the full schema.
"""

from app.models.ai_response_log import AiDecision, AiResponseLog
from app.models.contact import Contact, ContactStatus
from app.models.conversation import (
    AiMode,
    Channel,
    Conversation,
    ConversationState,
    ConversationStatus,
)
from app.models.conversation_event import ConversationEvent, EventType
from app.models.knowledge import (
    DocumentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SourceType,
)
from app.models.message import (
    ContentType,
    Direction,
    Message,
    MessageStatus,
    SenderType,
)
from app.models.user import User
from app.models.user_session import (
    RefreshToken,
    SessionEndReason,
    UserSession,
)
from app.models.whatsapp_account import (
    MessagingProviderName,
    WhatsAppAccount,
    WhatsAppAccountStatus,
)
from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceRole,
)

__all__ = [
    "AiDecision",
    "AiMode",
    "AiResponseLog",
    "Channel",
    "Contact",
    "ContactStatus",
    "ContentType",
    "Conversation",
    "ConversationEvent",
    "ConversationState",
    "ConversationStatus",
    "Direction",
    "DocumentStatus",
    "EventType",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeSource",
    "MembershipStatus",
    "Message",
    "MessageStatus",
    "MessagingProviderName",
    "RefreshToken",
    "SenderType",
    "SessionEndReason",
    "SourceType",
    "User",
    "UserSession",
    "WhatsAppAccount",
    "WhatsAppAccountStatus",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMembership",
    "WorkspaceRole",
    "WorkspaceStatus",
]
