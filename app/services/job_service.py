"""Running the queue: claiming work, and settling what became of it.

Deliberately knows no handler. What a job *does* lives in
`app/services/jobs.py`, which reaches the services that do it -- and those
services reach back here for the repository they enqueue through. Keeping
the protocol on this side of that line is what stops the two importing
each other.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.session import SessionDep
from app.integrations.messaging.base import MessagingProvider
from app.models.job import Job, JobKind
from app.repositories.job_repository import JobRepository

logger = logging.getLogger(__name__)

# How long to wait after the first failure, doubling each time. Thirty
# seconds is short enough that a provider blipping for a moment costs a
# customer nothing noticeable.
BACKOFF_BASE = timedelta(seconds=30)

# And the ceiling. An hour, because past that the thing being retried is
# not a blip and somebody needs to look at it -- the point of a backoff is
# to stop hammering something that is down, not to keep trying for a day.
BACKOFF_CEILING = timedelta(hours=1)


@dataclass(frozen=True)
class JobContext:
    """What a handler is given: a session, the queue, and the outside world.

    The providers are handed over rather than constructed, which is the
    same arrangement the request-time dispatchers use and for the same
    reason -- it is what keeps a test's fakes in force for work that runs
    long after the request that scheduled it.
    """

    session: Session
    jobs: JobRepository
    messaging: MessagingProvider
    now: datetime


class JobHandler(Protocol):
    """What one kind of job knows how to do."""

    def run(self, context: JobContext, job: Job) -> None:
        """Do the work, or raise.

        Raising is how a handler says "try again": the runner records the
        error and schedules the next attempt. Returning is how it says the
        job is done, including when it decided there was nothing to do.
        """
        ...


def backoff(attempts: int) -> timedelta:
    """How long before the next attempt.

    Doubling, capped. Written as a function rather than a table because
    the only property that matters is that it grows and stops growing.
    """
    delay = BACKOFF_BASE * (2 ** max(attempts - 1, 0))

    return min(delay, BACKOFF_CEILING)


class JobService:
    """One pass over the queue, and everything a pass has to get right.

    The handlers arrive as a mapping rather than being imported, so that
    this class can be tested against a handler that does exactly what a
    test needs -- and so that a job kind nobody has written a handler for
    fails as a job rather than as an import error at start-up.
    """

    def __init__(
        self,
        session: Session,
        jobs: JobRepository,
        handlers: Mapping[JobKind, JobHandler],
    ) -> None:
        self._session = session
        self._jobs = jobs
        self._handlers = handlers

    def reclaim_stalled(self) -> int:
        """Return work abandoned by a worker that died holding it."""
        stalled = get_settings().worker_stall_after_seconds
        reclaimed = self._jobs.reclaim_stalled(
            before=datetime.now(UTC) - timedelta(seconds=stalled),
        )
        self._session.commit()

        if reclaimed:
            logger.warning("Reclaimed %s stalled job(s)", reclaimed)

        return reclaimed

    def run_next(self, *, messaging: MessagingProvider) -> bool:
        """Take one due job and see it through. False if there was none.

        The claim is committed before the handler runs, which is what
        makes the claim mean anything: a worker that dies during the work
        has to leave a row saying it was taken, or a second worker picks
        the same job up immediately and does it twice.
        """
        now = datetime.now(UTC)
        job = self._jobs.claim(now=now)

        if job is None:
            return False

        self._session.commit()

        handler = self._handlers.get(job.kind)

        if handler is None:
            # A kind in the table that this deployment cannot do. Failed
            # outright rather than retried: another attempt runs the same
            # missing handler, and what is needed is a person.
            self._settle(job, error=f"No handler for {job.kind.value}", retry=False)

            return True

        try:
            handler.run(
                JobContext(
                    session=self._session,
                    jobs=self._jobs,
                    messaging=messaging,
                    now=now,
                ),
                job,
            )
        except AppError as exc:
            # This application's own vocabulary for "something outside
            # said no", which is the class of failure worth trying again.
            self._settle(job, error=str(exc), retry=True)
        except Exception as exc:
            # Anything else is a bug, and retrying a bug three times
            # produces three of the same stack trace. Recorded and stopped,
            # so one broken job does not take the worker down with it.
            logger.exception("Job %s raised", job.id)
            self._settle(job, error=repr(exc), retry=False)
        else:
            self._jobs.succeed(job, now=datetime.now(UTC))
            self._session.commit()

        return True

    def _settle(self, job: Job, *, error: str, retry: bool) -> None:
        """Write down what went wrong, and whether anything happens next.

        Rolled back first. A handler that failed may have left the session
        in a state where nothing can be written, and the one write that
        must survive a failed job is the record of it having failed.
        """
        self._session.rollback()

        now = datetime.now(UTC)
        again = retry and not job.exhausted

        self._jobs.fail(
            job,
            now=now,
            error=error,
            retry_at=now + backoff(job.attempts) if again else None,
        )
        self._session.commit()

        if not again:
            logger.error("Job %s gave up after %s attempt(s)", job.id, job.attempts)


def get_job_repository(session: SessionDep) -> JobRepository:
    return JobRepository(session)


JobRepositoryDep = Annotated[JobRepository, Depends(get_job_repository)]
