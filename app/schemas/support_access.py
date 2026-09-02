from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

# Long enough that "check" and "asked" do not pass, short enough that
# nobody is writing an essay to open a four-hour window. The number is a
# judgement rather than a rule, and the judgement is that a reason has to
# survive being read out to the customer whose account it is about --
# which is what the tenant's own audit entry does with it.
Reason = Annotated[str, Field(min_length=10, max_length=500)]


class SupportAccessRequest(BaseModel):
    """Asking to read one customer's data, for a stated reason.

    Both fields are the safeguard rather than paperwork.

    `reason` is required and has a floor on its length, because it ends
    up in the business's own audit log. "A staff member read your
    account" is alarming; "to investigate the delivery failure you
    reported on Tuesday" is an answer.

    `hours` is optional and capped. Omitted, it is the configured default
    -- four hours, which is a shift. Above the configured maximum the
    request is refused rather than shortened: somebody who believes they
    have two days and has four hours finds out in the middle of whatever
    they were investigating.
    """

    reason: Reason
    hours: Annotated[int | None, Field(ge=1, le=24)] = None


class SupportGrantRead(BaseModel):
    """One grant over a customer's account, live or historical.

    The staff member's address rather than their id, because this list is
    read by people asking who was in an account and an id sends them to
    another table to find out.

    `live` is computed rather than stored, from `expires_at`, `revoked_at`
    and the clock. There is no status column for the reason there is none
    on a session: a third thing that could disagree with the two
    timestamps is a third thing to keep in step.
    """

    id: UUID
    workspace_id: UUID
    staff_user_id: int
    staff_email: EmailStr
    reason: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    live: bool
