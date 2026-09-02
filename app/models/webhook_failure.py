import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class WebhookRefusal(StrEnum):
    """Why a delivery was not acted on.

    Three, and they mean genuinely different things to whoever is
    looking. A bad signature is either a misconfiguration or somebody
    probing; an unknown subject is a delivery for an account this
    deployment does not hold, which is what a shared provider app looks
    like from the wrong side; and a malformed body is the provider or a
    proxy having changed something.
    """

    BAD_SIGNATURE = "bad_signature"
    UNKNOWN_SUBJECT = "unknown_subject"
    MALFORMED = "malformed"


class WebhookFailure(Base):
    """One delivery this application refused, kept so somebody can see why.

    Written where a webhook is turned away, and it exists because that is
    the one failure in this system nobody hears about. The provider is
    told with a status code, the sender is a machine, and the customer
    whose storefront secret was mistyped simply notices that their orders
    stopped arriving -- days later, through support.

    **No body is stored, ever.** A delivery that failed to verify came
    from somebody unproven, so keeping what they sent would be keeping
    whatever a stranger chose to post at this endpoint. What is here is
    enough to recognise a pattern: which endpoint, which reason, from
    where, and when.

    Not workspace-scoped, and it cannot be: the whole problem with these
    is that the delivery could not be attributed to anybody. The provider
    and the reason are what a person groups by instead.
    """

    __tablename__ = "webhook_failures"

    __table_args__ = (
        # The only read there is: what has been refused lately, newest
        # first, sometimes narrowed to one provider.
        Index(
            "ix_webhook_failures_received_at",
            "provider",
            "received_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # A free string rather than an enum, and deliberately: the senders
    # here are WhatsApp, a payment provider and two storefronts, and the
    # set grows whenever an integration does. A vocabulary that had to be
    # migrated to add a row to a diagnostic table would be a vocabulary
    # somebody worked around.
    provider: Mapped[str] = mapped_column(String(64))

    reason: Mapped[WebhookRefusal] = mapped_column(
        enum_column(WebhookRefusal, name="webhook_refusal"),
    )

    # The route it was aimed at, so a reader can tell a storefront
    # delivery from a billing one without knowing this application's
    # routing table.
    path: Mapped[str] = mapped_column(String(255))

    # Best effort, like every other address recorded here. Useful for
    # exactly one thing: telling one misconfigured customer apart from
    # somebody sweeping the internet.
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"WebhookFailure(provider={self.provider!r}, reason={self.reason!r})"
