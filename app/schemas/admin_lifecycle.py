from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

# Same floor as a support grant's reason, and for the same argument: it
# reaches the customer's own audit log, where "unpaid" is a label and "the
# invoice of 3 March is 60 days overdue" is an answer.
Reason = Annotated[str, Field(min_length=10, max_length=500)]

# The workspace's slug, typed back. Not validated against a pattern here:
# what makes it a safeguard is that it has to match one particular
# workspace, which only the service can check.
ConfirmSlug = Annotated[str, Field(min_length=1, max_length=63)]


class SuspendRequest(BaseModel):
    """Why this account is being frozen.

    Required, because the customer reads it. A business that finds itself
    suspended and cannot see why has to open a ticket to be told
    something the platform already knew.
    """

    reason: Reason


class ConfirmSlugRequest(BaseModel):
    """Naming the workspace a destructive call is aimed at.

    The plan's rule for the operations that cannot be undone: the slug in
    the body, not just the id in the path. An id is copied from a list; a
    slug has to be read and typed, and the difference between those two
    acts is the safeguard.
    """

    confirm_slug: ConfirmSlug


class EraseNowRequest(ConfirmSlugRequest):
    """The slug, and a colleague who agreed to this erasure.

    Its own body rather than an optional field on the one above, because
    closing an account and destroying one are not the same act with a
    different flag: closing is reversible for thirty days and needs one
    person, and this is neither.
    """

    approval_id: UUID


class EraseAfterRequest(BaseModel):
    """When a closed account's records should be destroyed.

    Both directions are allowed, because both happen: a customer asking
    to be forgotten sooner, and a dispute or a legal hold pushing the
    date out. A date in the past is refused by the field rather than
    accepted and acted on -- erasing on the next sweep is what
    `erase-now` is for, and it asks for the slug.
    """

    erase_after: datetime


class SessionsRevoked(BaseModel):
    """How many sign-ins were ended.

    A number rather than 204, because it is the thing worth seeing: zero
    means the account was not signed in anywhere, which is a different
    answer to "somebody has my laptop" than three.
    """

    sessions_ended: int
