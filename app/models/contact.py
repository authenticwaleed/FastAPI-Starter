import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class ContactStatus(StrEnum):
    LEAD = "lead"
    CUSTOMER = "customer"
    # Nothing acts on this yet. It is what an abusive number becomes, and
    # what the messaging layer will check before answering one.
    BLOCKED = "blocked"


class Contact(Base):
    """One end customer of one business.

    The first table that holds somebody else's customers rather than this
    product's users, which is why every rule about workspace scoping stops
    being an abstraction here.
    """

    __tablename__ = "contacts"

    __table_args__ = (
        # Per workspace, deliberately not globally. The same person can be
        # a customer of two businesses using this product, and those are
        # two contacts who must not be able to see each other's history.
        UniqueConstraint(
            "workspace_id",
            "phone_number",
            name="uq_contacts_workspace_id_phone_number",
        ),
        # The business's own id for this person, in whatever system they
        # already had. Unique per workspace so a later Shopify or
        # WooCommerce sync can re-run without duplicating anybody.
        # PostgreSQL treats NULLs as distinct, so the many contacts with no
        # external id do not collide with each other.
        UniqueConstraint(
            "workspace_id",
            "external_id",
            name="uq_contacts_workspace_id_external_id",
        ),
        # The shape the list endpoint actually asks for: one workspace's
        # contacts, newest first. A plain index on workspace_id would be
        # redundant -- the unique constraints above already lead with it,
        # and PostgreSQL will use a composite index for a prefix of its
        # columns -- but neither of them helps with the sort.
        Index(
            "ix_contacts_workspace_id_created_at",
            "workspace_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    external_id: Mapped[str | None] = mapped_column(String(255), default=None)

    # Required, and the identity of a contact. This is a product that
    # reaches people on WhatsApp: somebody with no number is somebody it
    # cannot do anything with. Stored in E.164 so that a number typed into
    # the dashboard and the same number arriving from a provider are one
    # row rather than two.
    phone_number: Mapped[str] = mapped_column(String(16))

    name: Mapped[str | None] = mapped_column(String(150), default=None)

    email: Mapped[str | None] = mapped_column(String(320), default=None)

    status: Mapped[ContactStatus] = mapped_column(
        enum_column(ContactStatus, name="contact_status"),
        default=ContactStatus.LEAD,
        server_default=text("'lead'"),
    )

    # Free text rather than an enum: where a contact came from is a list
    # that grows with every integration, and a CHECK constraint that has to
    # be migrated for each one buys nothing.
    source: Mapped[str | None] = mapped_column(String(50), default=None)

    # Mapped to the column the plan names, under a different attribute:
    # `metadata` is taken on a declarative class by `Base.metadata`, and
    # shadowing it breaks the mapper rather than the attribute.
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

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"Contact(id={self.id!r}, workspace_id={self.workspace_id!r})"
