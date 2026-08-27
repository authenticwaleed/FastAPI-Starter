import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column
from app.models.product import MONEY


class OrderStatus(StrEnum):
    """Where an order has got to.

    The vocabulary a customer asks about, which is not the vocabulary a
    payment processor uses. "Has it shipped" is the question; `pending`,
    `confirmed`, `shipped`, `delivered`, `cancelled` and `refunded` are
    the six answers a shop actually gives.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class Order(Base):
    """One order, belonging to one contact of one workspace.

    The plan is explicit about why this is a table and not a document in
    the knowledge base: order status must be *queried*, not retrieved by
    similarity. A vector store asked "where is my order" returns the
    passage that reads most like the question, which for two customers
    with similar orders is a coin toss -- and the wrong side of that coin
    is one customer being told another's tracking number.

    So the contact is a column and the lookup is a WHERE clause. The
    composite foreign key means the database itself refuses an order
    attached to a contact from a different workspace.
    """

    __tablename__ = "orders"

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "contact_id"],
            ["contacts.workspace_id", "contacts.id"],
            ondelete="CASCADE",
            name="fk_orders_contact_in_same_workspace",
        ),
        # The shop's own order number, unique per workspace so a
        # storefront sync can re-run without duplicating anybody's order.
        UniqueConstraint(
            "workspace_id",
            "external_id",
            name="uq_orders_workspace_id_external_id",
        ),
        # What the list endpoint asks for: one workspace's orders, most
        # recent first.
        Index(
            "ix_orders_workspace_id_placed_at",
            "workspace_id",
            text("placed_at DESC NULLS LAST"),
            text("created_at DESC"),
        ),
        # And what the assistant asks for: this customer's orders. The
        # single most frequent query against this table once the product
        # is doing its job.
        Index(
            "ix_orders_workspace_id_contact_id",
            "workspace_id",
            "contact_id",
            text("placed_at DESC NULLS LAST"),
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

    # Required. An order nobody can be matched to is an order the
    # assistant can never safely answer a question about, because the
    # first thing it has to establish is whose it is.
    contact_id: Mapped[uuid.UUID]

    external_id: Mapped[str | None] = mapped_column(String(255), default=None)

    # What the customer calls it -- "#1042" -- as against the storefront's
    # internal id. Kept separately because customers quote this one back
    # and it is the string a lookup has to match.
    order_number: Mapped[str | None] = mapped_column(String(64), default=None)

    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus, name="order_status"),
        default=OrderStatus.PENDING,
        server_default=text("'pending'"),
    )

    currency: Mapped[str | None] = mapped_column(String(3), default=None)

    subtotal: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    shipping_total: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    total: Mapped[Decimal | None] = mapped_column(MONEY, default=None)

    # One block of text rather than parsed lines. Address formats differ
    # by country in ways no schema survives, and nothing here does
    # anything with an address except show it to a person.
    shipping_address: Mapped[str | None] = mapped_column(Text, default=None)

    tracking_number: Mapped[str | None] = mapped_column(String(128), default=None)
    tracking_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # When the customer placed it, which is not when this row was
    # written: a synced order was placed before this product ever saw it.
    placed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

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
        return f"Order(id={self.id!r}, status={self.status!r})"
