import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SupportGrant(Base):
    """Permission for one staff member to read one customer's data, until a date.

    The row the most dangerous phase of this plan is built around, and
    every column on it is a refusal of something easier.

    There is no "standing access" here. `expires_at` is not nullable,
    because a grant with no end is not a grant -- it is the permanent
    read access to every customer's account that this whole arrangement
    exists to replace. Whoever asks for one says how long they need, and
    the maximum is configuration rather than judgement.

    `reason` is not nullable either, and a minimum length is enforced at
    the schema. Free text, because no fixed list of reasons survives
    contact with real support work; required, because the reason is what
    makes the entry in the customer's own audit log mean something. "A
    staff member read your account" is alarming; "a staff member read
    your account to investigate the delivery failure you reported" is an
    answer.

    Rows are kept. A revoked or expired grant is the record that somebody
    had this access and when, which is exactly what an investigation
    needs and exactly what a delete would remove.
    """

    __tablename__ = "support_grants"

    __table_args__ = (
        # The lookup every read through a grant costs: has this staff
        # member got a live grant for this workspace. Narrow, indexed,
        # and asked on every request that reaches a customer's data.
        Index(
            "ix_support_grants_workspace_id_staff_user_id",
            "workspace_id",
            "staff_user_id",
        ),
        # What was granted over this business, newest first -- the
        # question an administrator asks, and the one a customer would
        # ask if they wrote in about it.
        Index(
            "ix_support_grants_workspace_id_created_at",
            "workspace_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # CASCADE, unlike the admin audit log's reference to the same table.
    # The two are different kinds of row: this one is a permission, which
    # is meaningless once the workspace is gone, while the log entry is
    # the record that somebody used it -- and that has to outlive the
    # erasure. Deleting a live permission with its subject is right;
    # deleting the evidence would not be.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    # The account, not the staff row. A colleague whose platform access
    # is revoked and later granted again keeps one staff row, and tying
    # a grant to that row would make its history harder to read than
    # tying it to the person.
    staff_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    reason: Mapped[str] = mapped_column(String(500))

    # Required. See the class docstring: this is the column that makes
    # this a grant rather than a permission.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Set when somebody ends it early -- the staff member finishing, or
    # an administrator taking it away. Null on a grant that simply ran
    # out, which is the ordinary ending and needs no timestamp of its own
    # because `expires_at` already says when.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def is_live_at(self, now: datetime) -> bool:
        """Whether this grant still opens anything, as of `now`.

        The clock is passed in rather than read here, like every other
        expiry in this application: a test should be able to ask what a
        grant looks like tomorrow without waiting until tomorrow.

        Two conditions and no status column, for the reason UserSession
        has none -- the state is a function of a timestamp and the clock,
        and storing it as well would be a third thing that could disagree
        with them. It also means a grant expires without anything having
        to run.
        """
        return self.revoked_at is None and self.expires_at > now

    def __repr__(self) -> str:
        return (
            f"SupportGrant(workspace_id={self.workspace_id!r}, "
            f"staff_user_id={self.staff_user_id!r})"
        )
