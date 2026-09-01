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

    try:
        with session.begin_nested():
            jobs.enqueue(
                kind=JobKind.SWEEP_AUTOMATIONS,
                payload={},
                dedupe_key=f"sweep_automations:{window}",
                # One attempt: another window is along in a few minutes,
                # and what this job does is enqueue more jobs.
                max_attempts=1,
            )
    except IntegrityError:
        # Another worker, or an earlier pass of this one, got there first.
        session.rollback()

    session.commit()


def tick(session: Session, *, messaging: MessagingProvider) -> int:
    """One pass: reclaim, plan, drain. Returns how many jobs ran."""
    jobs = JobRepository(session)
    service = JobService(session=session, jobs=jobs, handlers=CATALOGUE)

    service.reclaim_stalled()
    plan(session, jobs, now=datetime.now(UTC))

    ran = 0

    for _ in range(get_settings().worker_batch_size):
        if not service.run_next(messaging=messaging):
            break

        ran += 1

    return ran


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
        with sessions() as session:
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
