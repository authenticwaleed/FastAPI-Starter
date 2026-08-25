from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.models.workspace_membership import MembershipStatus, WorkspaceRole


class MemberRead(BaseModel):
    """One person on a workspace's team.

    Keyed by user id rather than membership id. A client asking "change
    Ada's role" knows who Ada is, not which row happens to record that she
    joined, and the membership id is an implementation detail that would
    only give the API a second identifier meaning the same thing.

    The name and email are here because a team list without them is a list
    of numbers. They come from a join, not a second request per row.
    """

    user_id: int
    name: str
    email: EmailStr
    role: WorkspaceRole
    status: MembershipStatus
    joined_at: datetime


class MemberUpdate(BaseModel):
    """Request body for changing what a member may do."""

    role: WorkspaceRole
