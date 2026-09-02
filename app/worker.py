"""The process that does the work nobody is waiting for.

Run it with `python -m app.worker`. It shares this application's models,
services and configuration and adds exactly one thing: a loop.

Two responsibilities per pass, and keeping them in that order matters.
First it plans -- makes sure the recurring work for this window exists --
and then it drains. Planning first means a worker started into an empty
queue has something to do on its first pass rather than on its second.

More than one may run at once. That is the point of claiming with
`FOR UPDATE SKIP LOCKED`, and the reason every enqueue carries a
deduplication key: two workers planning the same window write one row
between them.
"""

import logging
import signal
import sys
import time
from datetime import UTC, datetime
from types import FrameType

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import context
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine, get_session_factory
from app.integrations.messaging.base import MessagingProvider
from app.models.job import JobKind
from app.repositories.job_repository import JobRepository
from app.services.job_service import JobService
from app.services.jobs import CATALOGUE
from app.services.whatsapp_service import get_messaging_provider

logger = logging.getLogger(__name__)


class Stopping:
    """Whether the process has been asked to stop.

    A flag rather than an exception, because where a worker is allowed to
    stop is between jobs and not inside one. A SIGTERM arriving while a
    message is being handed to WhatsApp should finish that hand-off; a
    container that is killed mid-delivery leaves a claimed job for the
    stall reclaim to find, which works but takes five minutes.
    """

    def __init__(self) -> None:
        self.requested = False

    def listen(self) -> None:
        for received in (signal.SIGINT, signal.SIGTERM):
            signal.signal(received, self._request)

    def _request(self, signum: int, frame: FrameType | None) -> None:
        logger.info("Worker asked to stop; finishing the current job")
        self.requested = True


def plan(session: Session, jobs: JobRepository, *, now: datetime) -> None:
    """Make sure this window's recurring work is in the queue.

    The whole scheduler, and it is three lines because the deduplication
    key does the work: the window is part of the key, so every worker on
    every pass tries to enqueue the same row and at most one succeeds.

    A cron table would be the other way to do this, and would be a second
    thing to keep in step with the handlers. This has no state to drift --
    a worker that was switched off for an hour plans the window it wakes
    up in, not the twelve it missed, which is the right answer for a sweep
    that only ever looks at what is currently due.
    """
    window = int(now.timestamp()) // get_settings().worker_sweep_every_seconds

    for kind in (
        JobKind.SWEEP_AUTOMATIONS,
        JobKind.SWEEP_ERASURES,
        JobKind.SWEEP_SUPPORT_GRANTS,
    ):
        try:
            # A savepoint each, so the second sweep is still planned when
            # the first one is already there.
            with session.begin_nested():
                jobs.enqueue(
                    kind=kind,
                    payload={},
                    dedupe_key=f"{kind.value}:{window}",
                    # One attempt: another window is along in a few
                    # minutes, and what these jobs do is enqueue more jobs.
                    max_attempts=1,
                )
        except IntegrityError:
            # Another worker, or an earlier pass of this one, got there
            # first.
            logger.debug("%s is already planned for this window", kind.value)

    session.commit()


def tick(session: Session, *, messaging: MessagingProvider) -> int:
    """One pass: reclaim, plan, drain. Returns how many jobs ran."""
    jobs = JobRepository(session)
    service = JobService(session=session, jobs=jobs, handlers=CATALOGUE)

    service.reclaim_stalled()
    plan(session, jobs, now=datetime.now(UTC))
    _report_depth(jobs)

    ran = 0

    for _ in range(get_settings().worker_batch_size):
        if not service.run_next(messaging=messaging):
            break

        ran += 1

    return ran


def _report_depth(jobs: JobRepository) -> None:
    """Say how much is waiting, when anything is.

    A gauge in the log stream rather than a counter behind a scrape
    endpoint, for the reason every other measurement in this phase is one:
    it lands beside the lines that explain it, and reading "the queue was
    forty deep and every WhatsApp call took nine seconds" takes one query
    rather than two systems.

    Silent at zero, which is almost always. A worker that said "0" every
    two seconds for ever would bury the pass where it said forty.
    """
    depth = jobs.depth(now=datetime.now(UTC))

    if depth:
        logger.info("Queue depth", extra={"depth": depth})


def run_forever(stopping: Stopping | None = None) -> None:
    """Loop until asked to stop.

    A session per pass rather than one held open for the life of the
    process. A long-lived session accumulates every object it has ever
    loaded and holds a connection idle between jobs, and neither is worth
    it to save opening one every couple of seconds.

    Sleeps only when it found nothing. A pass that filled its batch goes
    straight round again, because a backlog is exactly when waiting two
    seconds is the wrong thing to do.
    """
    settings = get_settings()
    stopping = stopping or Stopping()
    stopping.listen()
    messaging = get_messaging_provider()
    sessions = get_session_factory()

    logger.info("Worker started")

    while not stopping.requested:
        # A request id per pass, so that the reclaim, the planning and
        # every job the pass ran can be pulled out of the log together --
        # the same thing the middleware does for a request, for the same
        # reason. A job's own handler binds the workspace it is for.
        with sessions() as session, context.bound(request_id=context.new_request_id()):
            ran = tick(session, messaging=messaging)

        if ran == 0 and not stopping.requested:
            time.sleep(settings.worker_poll_seconds)

    logger.info("Worker stopped")


def main() -> int:
    configure_logging()

    try:
        run_forever()
    finally:
        # The pool is closed here for the reason the API closes it in its
        # lifespan: otherwise the database is left to time the connections
        # out, and a worker restarted in a loop leaves a trail of them.
        get_engine().dispose()

    return 0


if __name__ == "__main__":
    sys.exit(main())
