import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import Job, JobKind, JobStatus


class JobRepository:
    """Every query against the jobs table lives here.

    The one that matters is `claim`. Everything else is bookkeeping around
    it: a queue is a table plus exactly one query that two workers can run
    at the same moment without both getting the same row.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        kind: JobKind,
        payload: dict[str, Any],
        workspace_id: uuid.UUID | None = None,
        run_at: datetime | None = None,
        dedupe_key: str | None = None,
        max_attempts: int = 5,
    ) -> Job:
        """Write the work down.

        Flushed and not committed, like a notification and for the same
        reason -- and here it is the reason the queue is in this database
        at all. The job belongs in the same transaction as whatever
        decided it was needed, so that a rolled-back message cannot leave
        a delivery scheduled for it.
        """
        job = Job(
            kind=kind,
            payload=payload,
            workspace_id=workspace_id,
            dedupe_key=dedupe_key,
            max_attempts=max_attempts,
        )

        if run_at is not None:
            job.run_at = run_at
        # Left unset otherwise, so that "due immediately" comes from the
        # column's server default -- the database's clock, which is the
        # same one `claim` compares against. An application's idea of now
        # is a few milliseconds of clock skew away from being a job that
        # is briefly not due yet.

        self._session.add(job)
        self._session.flush()

        return job

    def claim(self, *, now: datetime) -> Job | None:
        """Take one due job, in a way no second worker can take too.

        `FOR UPDATE SKIP LOCKED` is the whole mechanism. The row is locked
        by this transaction and every other worker's query steps over it
        rather than waiting -- which is the difference between two workers
        sharing a queue and two workers taking turns at it.

        The status is moved in the same transaction as the lock, so the
        claim outlives the lock being released: after the commit the row
        says `running` and nothing else will pick it up until it is either
        finished or reclaimed as stalled.
        """
        job = self._session.scalars(
            select(Job)
            .where(Job.status == JobStatus.PENDING, Job.run_at <= now)
            .order_by(Job.run_at, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()

        if job is None:
            return None

        job.status = JobStatus.RUNNING
        job.started_at = now
        job.attempts += 1
        self._session.flush()

        return job

    def succeed(self, job: Job, *, now: datetime) -> Job:
        job.status = JobStatus.SUCCEEDED
        job.finished_at = now
        job.last_error = None
        self._session.flush()

        return job

    def fail(
        self,
        job: Job,
        *,
        now: datetime,
        error: str,
        retry_at: datetime | None,
    ) -> Job:
        """Record what went wrong, and either try again later or stop.

        `retry_at` of None means there is nothing left to try. The row
        stays either way: a queue that deletes what it could not do is a
        queue nobody can debug, and the last error is on the row precisely
        because the row is what somebody looking at a stuck queue has in
        front of them.
        """
        job.last_error = error[:500]

        if retry_at is None:
            job.status = JobStatus.FAILED
            job.finished_at = now
        else:
            job.status = JobStatus.PENDING
            job.run_at = retry_at
            job.started_at = None

        self._session.flush()

        return job

    def reclaim_stalled(self, *, before: datetime) -> int:
        """Return abandoned claims to the queue.

        A worker that is killed mid-job leaves a row saying `running` and
        no process behind it. Nothing but a clock can tell that from a job
        that is taking a while, which is why `before` is passed in rather
        than computed here -- how long is too long is a deployment's
        decision, not this query's.

        Attempts are not wound back. A job that reliably kills its worker
        should exhaust its attempts like any other failure, or it is an
        infinite loop with a queue in front of it.
        """
        stalled = self._session.scalars(
            select(Job).where(
                Job.status == JobStatus.RUNNING,
                Job.started_at < before,
            )
        ).all()

        for job in stalled:
            job.status = JobStatus.PENDING
            job.started_at = None

        self._session.flush()

        return len(stalled)

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self._session.get(Job, job_id)

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        status: JobStatus | None = None,
    ) -> Sequence[Job]:
        where = [Job.workspace_id == workspace_id]

        if status is not None:
            where.append(Job.status == status)

        return self._session.scalars(
            select(Job).where(*where).order_by(Job.created_at.desc(), Job.id)
        ).all()
