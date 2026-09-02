from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.admin_approval import ApprovableAction

Reason = Annotated[str, Field(min_length=10, max_length=500)]


class ApprovalRequest(BaseModel):
    """Asking a colleague to agree to one specific act.

    `subject` is the workspace id for an erasure and the account id for a
    promotion, as text -- because those are different kinds of id and an
    approval has to be able to outlive the workspace it names.

    `role` is required for a promotion and ignored for an erasure. It is
    checked when the approval is spent, so an agreement given for `admin`
    cannot be used to grant `owner` -- which would defeat the only
    promotion this guards.
    """

    action: ApprovableAction
    subject: Annotated[str, Field(min_length=1, max_length=64)]
    reason: Reason
    role: str | None = None


class ApprovalRead(BaseModel):
    """One approval, and both people involved in it.

    Names rather than ids for the two people, because this list is read
    by somebody asking who agreed to what -- and an id sends them to
    another table to find out.

    `usable` is computed from the three timestamps and the clock, like
    every other liveness on this surface. What it does not say is whether
    *you* may spend it: that depends on who is asking, and the answer is
    no if you are the one who approved it.
    """

    id: UUID
    action: ApprovableAction
    subject: str
    reason: str
    requested_by: EmailStr | None
    approved_by: EmailStr | None
    approved_at: datetime | None
    consumed_at: datetime | None
    expires_at: datetime
    created_at: datetime
    metadata: dict[str, Any]
    usable: bool


class ApprovalPage(BaseModel):
    items: list[ApprovalRead]
    total: int
    page: int
    page_size: int
