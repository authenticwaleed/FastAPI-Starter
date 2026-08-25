from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.models.workspace_invitation import InvitationStatus
from app.models.workspace_membership import WorkspaceRole


def _lowercase(value: str) -> str:
    """Store the address in one case, so matching it is not a guess.

    An invitation is only accepted by the account it names, and nobody
    should be locked out of a workspace because they capitalised their
    address differently when they signed up.
    """
    return value.lower()


InvitedEmail = Annotated[
    EmailStr,
    Field(max_length=320),
    AfterValidator(_lowercase),
]


class InvitationCreate(BaseModel):
    email: InvitedEmail
    role: WorkspaceRole


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: WorkspaceRole
    status: InvitationStatus
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InvitationCreated(InvitationRead):
    """What creating an invitation returns, once.

    The token is here and nowhere else. It is not stored in readable form
    and no later response will repeat it, so this is the one chance to put
    it in a link -- which is what an email would do, once there is one.
    """

    token: str


class InvitationPreview(BaseModel):
    """What somebody holding the link may see before deciding.

    Enough to answer "who is asking me to join what, and as what". The
    token is the only credential involved, so this deliberately carries
    nothing that would matter to whoever else got hold of the link.
    """

    workspace_name: str
    workspace_slug: str
    email: EmailStr
    role: WorkspaceRole
    status: InvitationStatus
    expires_at: datetime
