import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column
from app.integrations.ecommerce.base import EcommerceProviderName


class EcommerceAccountStatus(StrEnum):
    CONNECTED = "connected"
    # Set when the shop owner uninstalls the app, which arrives as a
    # webhook. The row stays, and so does everything already synced: a
    # business that disconnects has not asked to lose its own catalogue.
    DISCONNECTED = "disconnected"


class EcommerceAccount(Base):
    """One workspace's connected storefront."""

    __tablename__ = "ecommerce_accounts"

    __table_args__ = (
        # One storefront per workspace, which is what makes "the
        # workspace's shop" a thing that can be spoken about in the
        # singular. More is a plan feature, and a plan feature is a
        # migration.
        UniqueConstraint("workspace_id", name="uq_ecommerce_accounts_workspace_id"),
        # A webhook arrives with a shop domain and nothing else to say who
        # it belongs to, so this is the lookup that turns a delivery into
        # a workspace -- and it has to be unique across all of them.
        UniqueConstraint(
            "shop_domain",
            name="uq_ecommerce_accounts_shop_domain",
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

    provider: Mapped[EcommerceProviderName] = mapped_column(
        enum_column(EcommerceProviderName, name="ecommerce_provider"),
    )

    # `acme.myshopify.com`. Lowercased on the way in, because it arrives
    # from three places -- a form, an OAuth callback, a webhook header --
    # and a lookup that turned on how somebody typed it would silently
    # fail to match a live connection.
    shop_domain: Mapped[str] = mapped_column(String(255))

    # Encrypted at rest with the same key provider tokens already use.
    # This one grants read access to a business's entire catalogue and
    # every order it has ever taken, which is why the settings refuse to
    # start production without a key.
    access_token_encrypted: Mapped[str] = mapped_column(Text)

    status: Mapped[EcommerceAccountStatus] = mapped_column(
        enum_column(EcommerceAccountStatus, name="ecommerce_account_status"),
        default=EcommerceAccountStatus.CONNECTED,
    )

    # When a full read of the shop last finished. Null until the first
    # one, which is what a dashboard shows as "not synced yet".
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
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
        return f"EcommerceAccount(id={self.id!r}, shop={self.shop_domain!r})"
