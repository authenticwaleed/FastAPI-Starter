import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class AuditEvent(StrEnum):
    """Something a person did that a business may later have to account for.

    The plan's list, and the shape of the names is part of it: `noun.verb`,
    past tense, because an audit log records what happened rather than what
    is being attempted. A row is written after the thing succeeded, so
    there is no `member.remove_failed` -- a refusal is not an event, it is
    the absence of one.

    Only administration. Every message a business sends is not an audit
    event; it is the work, and the inbox is already the record of it. What
    belongs here is what changes who can do what, what the assistant knows,
    and what the business is paying for.
    """

    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_UPDATED = "workspace.updated"

    MEMBER_INVITED = "member.invited"
    MEMBER_JOINED = "member.joined"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"

    WHATSAPP_CONNECTED = "whatsapp.connected"
    WHATSAPP_DISCONNECTED = "whatsapp.disconnected"

    KNOWLEDGE_DOCUMENT_UPLOADED = "knowledge.document_uploaded"
    KNOWLEDGE_DOCUMENT_DELETED = "knowledge.document_deleted"

    CONVERSATION_ASSIGNED = "conversation.assigned"
    CONVERSATION_CLOSED = "conversation.closed"
    CONVERSATION_AI_DISABLED = "conversation.ai_disabled"

    SUBSCRIPTION_CHANGED = "subscription.changed"

    # Added with Phase 27, which is when something first issued a key.
    # The column is a CHECK constraint rather than a native enum exactly
    # so that this was an ordinary drop and recreate -- see
    # app/db/types.py, which chose that trade for moments like this one.
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"


class AuditLog(Base):
    """One administrative act, kept.

    Append-only from the application's side, and that is enforced by
    omission: the repository can write a row and read rows, and there is
    no method anywhere that updates or deletes one. A log somebody can
    edit is not evidence of anything, and the businesses that ask for this
    are asking precisely because they need to be able to show a third
    party what happened.

    What is stored is the event and its particulars, not a sentence. A row
    saying "Ayesha was made an admin" is a decision about language taken
    at write time and frozen for ever; `member.role_changed` with the roles
    in `meta` renders in whatever language the reader's screen is in, and
    can still be counted.
    """

    __tablename__ = "audit_logs"

    __table_args__ = (
        # The only read there is: this workspace's history, newest first.
        # Ordered by the sequence rather than the timestamp for the reason
        # the column exists -- see below.
        Index(
            "ix_audit_logs_workspace_id_sequence",
            "workspace_id",
            text("sequence DESC"),
        ),
        # Narrowing that history to one person, which is the question an
        # investigation actually starts from: what did this account do.
        Index(
            "ix_audit_logs_workspace_id_actor_user_id",
            "workspace_id",
            "actor_user_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Strictly increasing, assigned by the database. Ordering an audit log
    # by created_at and breaking ties on the id would shuffle it: now() is
    # fixed for the length of a transaction, so several rows written in one
    # share a timestamp exactly, and a UUID then decides their order at
    # random. Never exposed; it orders, it does not identify.
    sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        unique=True,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    event: Mapped[AuditEvent] = mapped_column(
        enum_column(AuditEvent, name="audit_event"),
    )

    # Who did it. Null where nobody did: a subscription that changed
    # because a payment provider said so has no person behind it, and
    # naming one would put a row in the evidence that accuses somebody of
    # something they did not do.
    actor_user_id: Mapped[int | None] = mapped_column(
        # SET NULL rather than CASCADE: somebody leaving must not delete
        # the record of what they did while they were here. It does mean
        # the id goes when the account does, which is what the column
        # below is for.
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    # Who they were, copied at the moment they did it. The one
    # denormalised value in this table, and it earns its place: accounts
    # in this application are deleted rather than retired, so without it
    # an administrator could erase themselves from the record of what they
    # did by closing their own account -- which is the exact move an audit
    # log exists to defeat.
    #
    # Null only where `actor_user_id` is: nobody did it.
    actor_email: Mapped[str | None] = mapped_column(String(255), default=None)

    # The particulars: which document, which role, which member. Ids and
    # values, not prose -- what a reader sees is composed on the screen
    # in front of them.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"AuditLog(id={self.id!r}, event={self.event!r})"
