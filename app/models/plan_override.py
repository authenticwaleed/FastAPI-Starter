import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column
from app.services.plans import PlanTier


class PlanOverride(Base):
    """A plan the platform granted, which the payment provider knows nothing about.

    A pilot, a comp, an enterprise contract invoiced offline, a month of
    Business while somebody's migration is unpicked. All of them are the
    same shape: this workspace is entitled to that plan, whatever the
    provider says.

    A separate row rather than writing the tier onto `subscriptions.plan`,
    and the reason is the whole design. That column is a copy of what the
    provider said, kept current by webhooks -- so a value written into it
    by hand survives exactly until the next delivery about that
    subscription, and then reverts. Silently. Somebody would find out
    when a customer wrote in about features disappearing.

    Kept apart, the two never fight: the provider owns its column, the
    platform owns this one, and one function decides which wins.
    """

    __tablename__ = "plan_overrides"

    __table_args__ = (
        # One per workspace, which is what makes "the granted plan" a
        # thing that can be spoken about in the singular -- and what
        # makes replacing one an update rather than a second row that
        # quietly outranks the first.
        UniqueConstraint("workspace_id", name="uq_plan_overrides_workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # CASCADE: an entitlement is meaningless without the workspace it is
    # about. What has to outlive the workspace is the record that it was
    # granted, and that is in admin_audit_logs, which does not cascade.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    plan: Mapped[PlanTier] = mapped_column(
        enum_column(PlanTier, name="plan_override_tier"),
    )

    # Required, and it is read by the next person who wonders why this
    # business is on Business without paying for it. "Pilot until the
    # March contract lands" is an answer; a bare tier is a mystery
    # somebody eventually resolves by deleting the row.
    reason: Mapped[str] = mapped_column(String(500))

    granted_by_user_id: Mapped[int | None] = mapped_column(
        # SET NULL, like every actor reference here: a colleague leaving
        # must not delete the record of what they granted.
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    # Nullable, unlike a support grant's, and the difference is honest
    # rather than careless: a comp for a customer who negotiated one has
    # no natural end, and forcing a date would mean somebody inventing
    # one. What an unset date costs is that nothing expires it, so the
    # API warns when it is left out -- see app/schemas/admin_billing.py.
    #
    # An override past its date simply stops applying. Nothing runs.
    expires_at: Mapped[datetime | None] = mapped_column(
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

    def applies_at(self, now: datetime) -> bool:
        """Whether this grant is in force, as of `now`.

        No status column and nothing scheduled: an override with a date
        behind it stops matching, which is the same arrangement sessions
        and support grants use and for the same reason -- a flag would be
        a third thing that could disagree with the timestamp.
        """
        return self.expires_at is None or self.expires_at > now

    def __repr__(self) -> str:
        return f"PlanOverride(workspace_id={self.workspace_id!r}, plan={self.plan!r})"
