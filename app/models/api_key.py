import uuid
from datetime import datetime

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiKey(Base):
    """A credential a customer's own software authenticates with.

    What is stored is a digest and a fragment. The key itself exists once,
    in the response to the request that created it, and cannot be
    recovered from here afterwards -- which is the plan's instruction for
    this phase and also the only arrangement where a leaked copy of this
    table is not a set of working credentials.

    Nothing here says who created it. That is a question the audit log
    answers, and answering it twice would be two records that can
    disagree -- see AuditEvent.API_KEY_CREATED.
    """

    __tablename__ = "api_keys"

    __table_args__ = (
        # The lookup every authenticated request costs, so it is a unique
        # index and the digest is unsalted: an argument written out in
        # `hash_token`, and it applies with more force here, because this
        # runs on every call rather than once per invitation.
        UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        # A workspace's own keys, newest first, which is the management
        # screen and the only other read there is.
        Index(
            "ix_api_keys_workspace_id_created_at",
            "workspace_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    # Whatever the customer called it. The only thing distinguishing two
    # keys to a person, which is why the fragment below is stored beside it.
    name: Mapped[str] = mapped_column(String(100))

    # The first few characters of the key, kept so a list of them is
    # readable. Not a secret and not unique: it is a label, and the digest
    # is what identifies.
    key_prefix: Mapped[str] = mapped_column(String(16))

    key_hash: Mapped[str] = mapped_column(String(64))

    # When it was last presented. Stamped lazily -- see ApiKeyService --
    # because a write on every request to record the time of that request
    # is a cost with no reader.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # Null means it does not expire. Offered rather than imposed: a key
    # that stops working on a date nobody remembers choosing is an outage
    # in a customer's system, and the honest place for that decision is
    # the customer.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # Revoked rather than deleted, unlike the WhatsApp token: what would be
    # left behind there was a credential, and what is left behind here is a
    # digest of one. Keeping the row keeps `last_used_at` -- which is the
    # first thing anybody wants after revoking a key in a hurry.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def usable_at(self, now: datetime) -> bool:
        """Whether this key still authenticates anything.

        Both conditions in one place, because the two ways a key stops
        working have to be checked together and neither is the caller's to
        remember.
        """
        if self.revoked_at is not None:
            return False

        return self.expires_at is None or self.expires_at > now

    def __repr__(self) -> str:
        return f"ApiKey(id={self.id!r}, name={self.name!r})"
