"""Model package.

Importing this package registers every table on `Base.metadata`, which is
what Alembic autogenerate needs in order to see the full schema.
"""

from app.models.contact import Contact, ContactStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceRole,
)

__all__ = [
    "Contact",
    "ContactStatus",
    "MembershipStatus",
    "User",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMembership",
    "WorkspaceRole",
    "WorkspaceStatus",
]
