from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.audit_log import AuditEvent


class AuditActor(BaseModel):
    """Whoever did it, as much as is still known.

    Its own object rather than two flat fields, because the whole of it can
    be absent: an entry with no actor is a real entry -- a payment provider
    changed a subscription -- and `actor: null` says that in a way that
    `actor_name: null, actor_email: null` does not.

    Present with an id and no name where the account has since been
    deleted. The record of what they did survives them, which is the
    reason this table exists.
    """

    user_id: int | None
    name: str | None
    email: str | None


class AuditEntry(BaseModel):
    """One administrative act."""

    id: UUID
    event: AuditEvent
    actor: AuditActor | None
    # The particulars: which document, which role, which member. Ids and
    # values rather than a sentence, so a screen can render this in the
    # language its reader uses and a report can count it.
    metadata: dict[str, Any]
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    page: int
    page_size: int
