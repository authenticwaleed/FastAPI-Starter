import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class MessagingProviderName(StrEnum):
    """Which provider is behind the number.

    One value. Meta's Cloud API is what the MVP connects to; Twilio and
    the resellers are the reason this is a column rather than an
    assumption baked into the adapter.
    """

    META_CLOUD = "meta_cloud"


class WhatsAppAccountStatus(StrEnum):
    CONNECTED = "connected"
    # Set when the provider rejects the credentials. Nothing writes it
    # yet; sending records the failure on the message instead.
    DISCONNECTED = "disconnected"


class WhatsAppAccount(Base):
    """One workspace's connected WhatsApp Business number."""

    __tablename__ = "whatsapp_accounts"

    __table_args__ = (
        # One number per workspace, which is what makes "the workspace's
        # WhatsApp account" a thing that can be spoken about in the
        # singular. More numbers is a plan feature, and a plan feature is
        # a migration.
        UniqueConstraint("workspace_id", name="uq_whatsapp_accounts_workspace_id"),
        # The webhook arrives with a phone number id and nothing else to
        # say who it belongs to. This is the lookup that turns a delivery
        # into a workspace, so it has to be unique across all of them.
        UniqueConstraint(
            "external_phone_number_id",
            name="uq_whatsapp_accounts_external_phone_number_id",
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

    provider: Mapped[MessagingProviderName] = mapped_column(
        enum_column(MessagingProviderName, name="messaging_provider"),
        default=MessagingProviderName.META_CLOUD,
    )

    # The business's own WhatsApp number, in E.164 like every other number
    # in this schema.
    phone_number: Mapped[str] = mapped_column(String(16))

    external_phone_number_id: Mapped[str] = mapped_column(String(64))

    external_business_account_id: Mapped[str | None] = mapped_column(
        String(64),
        default=None,
    )

    # Encrypted, never the token. The column is named for what it holds so
    # that nobody reading a query result mistakes it for something they
    # can use, and it is Text because ciphertext is longer than its input
    # and Fernet's length is not worth pinning down.
    access_token_encrypted: Mapped[str] = mapped_column(Text)

    status: Mapped[WhatsAppAccountStatus] = mapped_column(
        enum_column(WhatsAppAccountStatus, name="whatsapp_account_status"),
        default=WhatsAppAccountStatus.CONNECTED,
    )

    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
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
        # Deliberately without the token column, encrypted or not. A repr
        # ends up in tracebacks, debuggers and log lines.
        return (
            f"WhatsAppAccount(id={self.id!r}, "
            f"workspace_id={self.workspace_id!r}, "
            f"phone_number={self.phone_number!r})"
        )
