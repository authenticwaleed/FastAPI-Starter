import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
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


class ApprovableAction(StrEnum):
    """The acts that need a second person.

    Two, and the list is short on purpose. Requiring a colleague for
    everything would mean nobody could do anything alone at three in the
    morning, and a rule people cannot follow is a rule they route around
    -- by keeping a standing approval, or by sharing an account.

    These two earn it. One destroys a business's records with no way
    back, and the other creates somebody who can do the first.
    """

    ERASE_WORKSPACE = "erase_workspace"
    GRANT_STAFF_OWNER = "grant_staff_owner"


class AdminApproval(Base):
    """One colleague agreeing, in advance, to something about to be done.

    A row rather than a flag on the request, because the point is that
    two people were involved and that has to be checkable afterwards: who
    asked, who agreed, when, and what exactly they agreed to.

    `subject` is the part worth being careful about. An approval is for
    *this* workspace or *that* account, never for the action in general
    -- otherwise a colleague agreeing to erase a test workspace would
    have agreed to erase any of them.
    """

    __tablename__ = "admin_approvals"

    __table_args__ = (
        # The lookup spending an approval costs: the pending ones for this
        # act and this subject.
        Index(
            "ix_admin_approvals_action_subject",
            "action",
            "subject",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    action: Mapped[ApprovableAction] = mapped_column(
        enum_column(ApprovableAction, name="approvable_action"),
    )

    # What it is about, as text rather than a foreign key. Two reasons,
    # and the second is the one that decides it: the subject of an
    # erasure is a workspace and the subject of a promotion is an
    # account, so no one column could reference both -- and an approval
    # for an erasure has to outlive the workspace it names, exactly like
    # the audit entry beside it.
    subject: Mapped[str] = mapped_column(String(64))

    # Free text, and read by the person deciding whether to agree. An
    # approval nobody can evaluate is a rubber stamp with extra steps.
    reason: Mapped[str] = mapped_column(String(500))

    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    # Null until somebody agrees. The whole state of an approval is these
    # two timestamps and the clock, like every other expiry here.
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # Set when it is spent. One approval, one act: without this, a
    # colleague's agreement to erase one workspace would be reusable
    # every time somebody wanted to erase it again -- which sounds
    # harmless until the workspace is restored and erased twice.
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # Short. The point of the second person is that they are looking at
    # the same situation as the first; an approval collected in the
    # morning and spent in the evening is one signature on a decision,
    # not two.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # What was actually agreed to, beyond the subject: which rank, which
    # slug. Checked when the approval is spent, so a request approved for
    # `support` cannot be spent granting `owner`.
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

    def usable_at(self, now: datetime) -> bool:
        """Whether this approval still authorises anything.

        Approved, unspent, and not yet expired. Who may spend it is a
        separate question and deliberately not here -- it depends on who
        is asking, and this object does not know.
        """
        return (
            self.approved_at is not None
            and self.consumed_at is None
            and self.expires_at > now
        )

    def __repr__(self) -> str:
        return f"AdminApproval(action={self.action!r}, subject={self.subject!r})"
