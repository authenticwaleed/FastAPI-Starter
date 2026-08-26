"""Model package.

Importing this package registers every table on `Base.metadata`, which is
what Alembic autogenerate needs in order to see the full schema.
"""

from app.models.contact import Contact, ContactStatus
from app.models.conversation import (
    AiMode,
    Channel,
    Conversation,
    ConversationStatus,
)
from app.models.message import (
    ContentType,
    Direction,
    Message,
    MessageStatus,
    SenderType,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceRole,
)

__all__ = [
    "AiMode",
    "Channel",
    "Contact",
    "ContactStatus",
    "ContentType",
    "Conversation",
    "ConversationStatus",
    "Direction",
    "MembershipStatus",
    "Message",
    "MessageStatus",
    "SenderType",
    "User",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMembership",
    "WorkspaceRole",
    "WorkspaceStatus",
]
