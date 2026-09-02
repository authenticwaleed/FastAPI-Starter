import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class StaffRole(StrEnum):
    """What somebody who runs Baton itself may do, in ascending order.

    Not to be confused with WorkspaceRole, which is about a customer's
    own team. These three are about the business that operates the
    product: a support engineer answering a ticket, an administrator
    suspending an account that is not paying, and whoever decides which
    colleagues get either power.

    Three rather than four, and strictly ordered rather than a matrix,
    for the same reason the tenant roles are a fixed list: a permission
    engine is a product in its own right, and the shape of the work here
    is a ladder -- everything support can do, an admin can do too.
    """

    SUPPORT = "support"
    ADMIN = "admin"
    OWNER = "owner"


# Least authority first, so an index into it is a rank.
_PRECEDENCE = (StaffRole.SUPPORT, StaffRole.ADMIN, StaffRole.OWNER)


def permits(role: StaffRole, needed: StaffRole) -> bool:
    """Whether `role` is `needed` or above it.

    A ladder rather than the tenant side's `outranks`, and the difference
    is deliberate. There, the question is whether one person may act on
    another, so equal roles must not qualify. Here the question is
    whether a role reaches a route, so equal roles must.
    """
    return _PRECEDENCE.index(role) >= _PRECEDENCE.index(needed)


class StaffMember(Base):
    """One ordinary account, promoted to run the platform.

    A table rather than `users.is_staff`, and that is the whole design.
    A boolean can say that somebody is privileged; it cannot say who
    made them so, when, or that it was taken away again -- and those are
    the three questions asked after an incident, by people who are not
    going to accept "the column was true" as an answer.

    Promoted rather than separate, so a staff member has one account,
    one password and one set of sessions. What differs is not how they
    sign in but what they may reach once they have, and how closely the
    reaching is watched.

    Rows are kept when access is withdrawn. A revoked row is the record
    that somebody once had this power, which is exactly the row an
    investigation needs and exactly the row a delete would remove.
    """

    __tablename__ = "staff_members"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # One row per account, live or revoked. Unique, so that reinstating a
    # colleague updates the row that already records their history rather
    # than starting a second one beside it -- the same argument
    # WorkspaceMembership makes for its unique constraint.
    #
    # CASCADE, because this row says something about an account and means
    # nothing without it. What must outlive the account is the record of
    # what they did, and that is admin_audit_logs, which keeps the address
    # rather than the id for exactly this reason.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
    )

    role: Mapped[StaffRole] = mapped_column(
        enum_column(StaffRole, name="staff_role"),
    )

    # Who promoted them. Null for the first owner and only for them:
    # somebody has to be able to grant the power before anybody holds it,
    # so the first row is seeded from the command line by whoever runs
    # the deployment. Every row after it names a person.
    #
    # SET NULL rather than CASCADE, like the audit log's actor: a
    # colleague leaving must not delete the record of who they promoted.
    granted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Set when access is withdrawn, and cleared if it is ever given back.
    # There is no status column for the reason UserSession has none: the
    # state is a function of this one timestamp, and storing it as well
    # would be a second thing that could disagree with it.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    @property
    def is_live(self) -> bool:
        """Whether this row still authorises anything.

        No clock involved, unlike a session or an API key: staff access
        does not lapse on its own. What is time-boxed is reaching a
        particular customer's data, which is a support grant and a
        different table -- this is only the door to the console.
        """
        return self.revoked_at is None

    def __repr__(self) -> str:
        return f"StaffMember(user_id={self.user_id!r}, role={self.role!r})"
