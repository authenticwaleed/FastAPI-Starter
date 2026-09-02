from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.admin_audit_log import AdminAction


class AdminAuditActor(BaseModel):
    """Whichever staff member did it, as much as is still known.

    Its own object rather than flat fields, like the tenant log's actor,
    because the whole of it can be absent: the first owner was granted
    before anybody existed to grant it, and `actor: null` says that in a
    way two null strings do not.

    Present with an address and no id where the account has since been
    deleted. The foreign key nulled the id when the row went; the address
    was copied at the time so that it did not go with it.
    """

    user_id: int | None
    name: str | None
    email: str | None


class AdminAuditSubject(BaseModel):
    """Which workspace an entry was about, if any.

    The id and the slug together, and the slug is the half that matters.
    Once a workspace is erased the id is nulled -- that reference does not
    cascade, on purpose -- and what is left saying whose account this
    entry concerned is the name copied beside it.
    """

    workspace_id: UUID | None
    workspace_slug: str | None


class AdminAuditEntry(BaseModel):
    """One thing a staff member did on the platform surface."""

    id: UUID
    action: AdminAction
    actor: AdminAuditActor | None
    subject: AdminAuditSubject | None
    # The other account this was about, where there was one: a colleague
    # promoted, a customer whose sessions were ended.
    target_user_id: int | None
    # The particulars: which role, which page, which narrowing. Ids and
    # values rather than a sentence, so a screen can render this in the
    # language its reader uses and a report can count it.
    metadata: dict[str, Any]
    # Where it came from. Best effort and decides nothing -- it is here
    # because the question asked after an incident is whether an entry
    # looks like the colleague it names.
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


class AdminAuditPage(BaseModel):
    items: list[AdminAuditEntry]
    total: int
    page: int
    page_size: int
