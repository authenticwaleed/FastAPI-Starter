"""Model package.

Importing this package registers every table on `Base.metadata`, which is
what Alembic autogenerate needs in order to see the full schema.
"""

from app.models.ai_response_log import AiDecision, AiResponseLog
from app.models.api_key import ApiKey
from app.models.audit_log import AuditEvent, AuditLog
from app.models.automation import (
    Automation,
    AutomationKind,
    AutomationRun,
    AutomationStatus,
    AutomationTrigger,
    RunStatus,
)
from app.models.contact import Contact, ContactStatus
from app.models.conversation import (
    AiMode,
    Channel,
    Conversation,
    ConversationState,
    ConversationStatus,
)
from app.models.conversation_event import ConversationEvent, EventType
from app.models.ecommerce_account import (
    EcommerceAccount,
    EcommerceAccountStatus,
)
from app.models.job import Job, JobKind, JobStatus
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
from app.models.notification import Notification, NotificationKind
from app.models.order import Order, OrderStatus
from app.models.product import Product, ProductStatus, ProductVariant
from app.models.subscription import (
    BillingEvent,
    BillingProviderName,
    Subscription,
    SubscriptionStatus,
)
from app.models.usage_record import UsageMetric, UsageRecord
from app.models.user import User
from app.models.user_session import (
    RefreshToken,
    SessionEndReason,
    UserSession,
)
from app.models.user_token import UserToken, UserTokenPurpose
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
    "ApiKey",
    "AuditEvent",
    "AuditLog",
    "Automation",
    "AutomationKind",
    "AutomationRun",
    "AutomationStatus",
    "AutomationTrigger",
    "BillingEvent",
    "BillingProviderName",
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
    "EcommerceAccount",
    "EcommerceAccountStatus",
    "EventType",
    "Job",
    "JobKind",
    "JobStatus",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeSource",
    "MembershipStatus",
    "Message",
    "MessageStatus",
    "MessagingProviderName",
    "Notification",
    "NotificationKind",
    "Order",
    "OrderStatus",
    "Product",
    "ProductStatus",
    "ProductVariant",
    "RefreshToken",
    "RunStatus",
    "SenderType",
    "SessionEndReason",
    "SourceType",
    "Subscription",
    "SubscriptionStatus",
    "UsageMetric",
    "UsageRecord",
    "User",
    "UserSession",
    "UserToken",
    "UserTokenPurpose",
    "WhatsAppAccount",
    "WhatsAppAccountStatus",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMembership",
    "WorkspaceRole",
    "WorkspaceStatus",
]
