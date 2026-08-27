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
    Numeric,
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

# Money is Numeric, never a float. A float cannot hold 0.10, and a price
# that is wrong in the fourth decimal place becomes a total that is wrong
# in the first once it is multiplied by a quantity.
#
# Two decimal places, which covers PKR, AED, SAR, USD, EUR and every other
# currency this product's customers price in. The three-decimal ones --
# KWD, BHD, OMR -- would need a migration, and pretending otherwise by
# storing four places nobody uses would make every number harder to read
# for the sake of a currency nobody has asked for.
MONEY = Numeric(12, 2)


class ProductStatus(StrEnum):
    """Whether the business is selling this.

    The assistant is told about `active` products only. Talking about a
    draft is worse than saying nothing: the customer asks for something
    the business has not decided to sell yet.
    """

    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


class Product(Base):
    """Something a business sells, in structured form.

    The point of the table is the assistant. A price or a stock level
    living only in an uploaded PDF reaches the model as a passage it has
    to read and may misread; here it is a column, looked up by a query,
    and the answer is either right or absent. The plan puts it plainly:
    the AI uses a product lookup rather than hallucinating inventory.
    """

    __tablename__ = "products"

    __table_args__ = (
        # The business's own id for this in whatever system it came from,
        # unique per workspace so a Shopify or WooCommerce sync can re-run
        # without duplicating the catalogue. NULLs are distinct in
        # PostgreSQL, so hand-entered products with no external id do not
        # collide with each other.
        UniqueConstraint(
            "workspace_id",
            "external_id",
            name="uq_products_workspace_id_external_id",
        ),
        # The target of the composite foreign key on variants, which is
        # what lets a variant say "this product, in this workspace"
        # rather than "this product, and trust me".
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_products_workspace_id_id",
        ),
        Index(
            "ix_products_workspace_id_created_at",
            "workspace_id",
            text("created_at DESC"),
        ),
        # What a customer's question actually searches: this workspace's
        # products, by name. A plain btree serves the prefix and the
        # equality cases; the ILIKE '%...%' the search falls back to is a
        # scan of one workspace's catalogue, which is a few hundred rows.
        Index("ix_products_workspace_id_name", "workspace_id", "name"),
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

    name: Mapped[str] = mapped_column(String(255))

    description: Mapped[str | None] = mapped_column(Text, default=None)

    status: Mapped[ProductStatus] = mapped_column(
        enum_column(ProductStatus, name="product_status"),
        default=ProductStatus.ACTIVE,
        server_default=text("'active'"),
    )

    # Nullable, because a business whose prices are all per-variant has no
    # price at this level and a zero here would be a lie the assistant
    # would repeat.
    price: Mapped[Decimal | None] = mapped_column(MONEY, default=None)

    # ISO 4217, uppercased on the way in. Stored per product rather than
    # per workspace because a catalogue synced from two storefronts can
    # carry two, and a single workspace-wide currency would silently
    # relabel half of it.
    currency: Mapped[str | None] = mapped_column(String(3), default=None)

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
        return f"Product(id={self.id!r}, name={self.name!r})"


class ProductVariant(Base):
    """One buyable version of a product: a size, a colour, a pack.

    Carries the workspace as well as the product, and the foreign key is
    composite for that reason. A plain product_id would let a variant be
    attached to another business's product by anybody who guessed an id;
    the pair has to exist together in `products`, so it cannot.
    """

    __tablename__ = "product_variants"

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "product_id"],
            ["products.workspace_id", "products.id"],
            ondelete="CASCADE",
            name="fk_product_variants_workspace_id_product_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "external_id",
            name="uq_product_variants_workspace_id_external_id",
        ),
        # A SKU is by definition the business's unique handle for a thing.
        # Unique per workspace, and NULL for the many businesses that do
        # not keep them -- NULLs being distinct is what allows that.
        UniqueConstraint(
            "workspace_id",
            "sku",
            name="uq_product_variants_workspace_id_sku",
        ),
        Index(
            "ix_product_variants_workspace_id_product_id",
            "workspace_id",
            "product_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # Named in the composite foreign key above rather than carrying one
    # of its own, which is what makes it impossible for a variant to
    # reach across the tenant boundary.
    workspace_id: Mapped[uuid.UUID]

    product_id: Mapped[uuid.UUID]

    external_id: Mapped[str | None] = mapped_column(String(255), default=None)

    sku: Mapped[str | None] = mapped_column(String(100), default=None)

    # "Medium / Black". Nullable because a product with one variant often
    # has nothing to call it.
    title: Mapped[str | None] = mapped_column(String(255), default=None)

    # Nullable, and null means "the product's price applies" rather than
    # "free".
    price: Mapped[Decimal | None] = mapped_column(MONEY, default=None)

    # Three states, not two. Null is "this business does not track stock",
    # 0 is "out of stock", and a number is a number. Collapsing the first
    # two would have the assistant telling customers something is
    # unavailable when the truth is that nobody counted -- which is the
    # kind of confident wrong answer this whole table exists to prevent.
    stock_quantity: Mapped[int | None] = mapped_column(default=None)

    # {"size": "M", "color": "Black"}, exactly as the plan has it. Free
    # shape because the axes a business varies on are its own.
    attributes: Mapped[dict[str, Any]] = mapped_column(
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
        return f"ProductVariant(id={self.id!r}, sku={self.sku!r})"
