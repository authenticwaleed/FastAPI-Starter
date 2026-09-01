import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class JobKind(StrEnum):
    """Work this application knows how to do later.

    A closed vocabulary rather than a handler name in a string, for the
    reason every other enum here is one: a queue holding the name of a
    function nobody has written any more is a row that fails for ever, and
    the database is where that should be caught.
    """

    # Deliver a message that is written into a thread and has not gone
    # out. The retry worker the message service has been describing since
    # WhatsApp was connected.
    DELIVER_MESSAGE = "deliver_message"
    # The timer half. Fans out to one RUN_DUE_AUTOMATIONS per workspace
    # that has a scheduled automation switched on, so that one business's
    # failure is not every business's.
    SWEEP_AUTOMATIONS = "sweep_automations"
    RUN_DUE_AUTOMATIONS = "run_due_automations"


class JobStatus(StrEnum):
    """Where a job has got to.

    `running` is a claim rather than a description: a worker that dies
    holding one leaves it here, and the reclaim in JobService is what
    turns it back into work. That is why `started_at` is written beside
    it -- without a time, a stalled job and a busy one look identical.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    # Out of attempts. Kept rather than deleted: the last error is on the
    # row, and a queue that silently drops what it could not do is a queue
    # nobody can debug.
    FAILED = "failed"


class Job(Base):
    """One piece of work to be done after the request that caused it.

    In PostgreSQL rather than in a broker, and that is the phase's whole
    decision. The plan says to introduce a job system only when needed and
    to choose the queue when the requirements are clear; the requirement
    that decides it is transactional enqueue.

    Everything deferred in this application is written in the same
    transaction as the thing that caused it -- a notification, a usage
    record, an audit entry -- so that neither can exist without the other.
    A job in a separate broker cannot have that. Enqueued before the
    commit it survives a rollback and schedules work for something that
    never happened; enqueued after, it is lost in the gap. Here it is one
    write, and `SELECT ... FOR UPDATE SKIP LOCKED` is the rest.

    What would change this is throughput: a worker polling a table it
    shares with every application query is fine at hundreds of jobs a
    minute and is not the shape for tens of thousands. That is a good
    problem and a later decision.
    """

    __tablename__ = "jobs"

    __table_args__ = (
        # At most one job for a given piece of work. The key is supplied
        # by whoever enqueues -- one delivery per message, one sweep per
        # window -- which is what makes enqueuing safe to do twice, from
        # a retried webhook or from two workers ticking at once.
        #
        # Nullable, and a plain unique constraint rather than a partial
        # index because PostgreSQL already treats nulls as distinct: a job
        # with no key never collides with anything.
        UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),
        # The claim, which is the only query that runs on a schedule:
        # what is pending and due, oldest first.
        Index("ix_jobs_status_run_at", "status", "run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Null for work that is not about one business -- the sweep that fans
    # out to all of them. Everything else carries it, so that a queue
    # backing up can be read per tenant rather than as one number.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        default=None,
    )

    kind: Mapped[JobKind] = mapped_column(enum_column(JobKind, name="job_kind"))

    # What the handler needs, and only ids. Not the objects themselves: a
    # job runs minutes after it was written, and a payload carrying a copy
    # of a message would deliver the text as it was rather than as it is.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, name="job_status"),
        default=JobStatus.PENDING,
        server_default=text("'pending'"),
    )

    dedupe_key: Mapped[str | None] = mapped_column(String(200), default=None)

    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    # How many times this particular job is worth trying. On the row
    # rather than in the handler, because it is a property of the work:
    # delivering a message is worth several attempts over an hour, and
    # fanning out a sweep that will be enqueued again in five minutes is
    # worth one.
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=5,
        server_default=text("5"),
    )

    # When it becomes eligible. Set forward on every failure, which is how
    # the backoff is stored -- there is no sleeping worker holding a
    # retry, only a row that is not due yet.
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # What went wrong last time, in the words the application used. Kept on
    # the row rather than only in the log, because the row is what somebody
    # looking at a stuck queue actually has in front of them.
    last_error: Mapped[str | None] = mapped_column(String(500), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts

    def __repr__(self) -> str:
        return f"Job(id={self.id!r}, kind={self.kind!r}, status={self.status!r})"
