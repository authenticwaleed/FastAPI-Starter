import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class UsageMetric(StrEnum):
    """Everything a workspace uses up or takes up.

    One vocabulary for two questions that a business does not experience
    as two: what have I spent this month, and how much room is left. The
    plan's limits are named in `app/services/plans.py` in the language of
    what a plan sells; these are named in the language of what is
    consumed, and `LIMIT_METRICS` in the usage service is the one place
    the two meet.

    Some of these are a running total that resets each period and some
    are a level that is simply true right now. Which is which is decided
    in `app/services/usage_service.py`, because it is a fact about how a
    number is obtained rather than about what it means -- and only the
    running totals ever become rows in the table below.
    """

    # Spent, and gone when the period turns over.
    AI_RESPONSES = "ai_responses"
    AI_TOKENS = "ai_tokens"
    WHATSAPP_MESSAGES = "whatsapp_messages"
    # True right now, whenever it is asked. Counted from the rows that
    # define them rather than accumulated, because a level assembled from
    # a ledger of additions and removals is a number that drifts.
    ACTIVE_CONTACTS = "active_contacts"
    TEAM_MEMBERS = "team_members"
    WHATSAPP_NUMBERS = "whatsapp_numbers"
    KNOWLEDGE_DOCUMENTS = "knowledge_documents"
    KNOWLEDGE_TOKENS = "knowledge_tokens"


class UsageRecord(Base):
    """One thing a workspace used, written where it was used.

    The plan's instruction for this phase is the whole of the design:
    create usage events at the service boundary, and do not calculate
    billing-critical usage from unreliable logs. So this is not a view
    over the tables that happen to record something similar -- it is a
    ledger, appended to at the moment the assistant answers or a message
    goes out, and it is what a plan limit is checked against.

    The difference is not pedantry. `ai_response_logs` has a row for every
    decision the pipeline reached, including the ones where it declined to
    answer and spent nothing; counting those charged a business for
    switching the assistant off. A meter should say what was used.

    Append-only. Nothing here is ever updated, and a correction is another
    row, because a number somebody is billed from should be reconstructable
    rather than merely current.
    """

    __tablename__ = "usage_records"

    __table_args__ = (
        # What makes the ledger safe to write from a webhook. A provider
        # redelivers whatever it did not get a prompt 200 for, and the
        # thing being counted twice here is what somebody is charged --
        # so every event names the row that caused it, and a second
        # attempt loses at the insert rather than quietly doubling a
        # month's usage.
        UniqueConstraint(
            "workspace_id",
            "metric",
            "source_id",
            name="uq_usage_records_workspace_id_metric_source_id",
        ),
        # The only read that matters: one metric's total for one period.
        # The period is on the row rather than derived from `created_at`
        # at read time, which is what keeps a total from moving when a
        # subscription's dates change under it.
        Index(
            "ix_usage_records_workspace_id_metric_period_start",
            "workspace_id",
            "metric",
            "period_start",
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

    metric: Mapped[UsageMetric] = mapped_column(
        enum_column(UsageMetric, name="usage_metric"),
    )

    # Big, because tokens are counted in millions and an integer that
    # overflows in the second year of a successful customer is not a
    # column anybody wants to migrate under load.
    quantity: Mapped[int] = mapped_column(BigInteger)

    # Which period this was assigned to, settled when it was written and
    # never revisited. Half open -- start included, end excluded -- like
    # every other period in this application, so that two consecutive
    # periods neither overlap nor leave a gap.
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # The row that caused this: the log line for an answer, the message
    # for a send. Kept as a bare id rather than a foreign key because it
    # points at a different table depending on the metric, and because a
    # meter should outlive the thing it measured -- a business that
    # deletes a conversation has still used what it used.
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"UsageRecord(metric={self.metric!r}, quantity={self.quantity!r})"
