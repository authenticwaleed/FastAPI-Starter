"""Phase 28 acceptance: work that happens after the request has gone.

The queue is a table, so most of what has to be right is about one query:
that a claimed job is claimed, that a job not yet due is not, that a
failure comes back later and a bug does not come back at all.

One property this suite does not exercise is the concurrent one. Claiming
uses `FOR UPDATE SKIP LOCKED`, which only means anything across two
connections, and every test here runs inside a single transaction that a
second connection cannot see. What is tested instead is the consequence
that survives the commit: a claimed job says `running`, and nothing claims
a job that says `running`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import MessagingProviderError
from app.models.automation import AutomationKind
from app.models.job import Job, JobKind, JobStatus
from app.models.message import MessageStatus
from app.repositories.job_repository import JobRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.job_service import JobContext, JobService, backoff
from app.services.jobs import CATALOGUE
from app.services.plans import PlanTier
from app.worker import plan, tick
from tests.support.messaging import FakeMessagingProvider
from tests.support.tenants import Tenant


@pytest.fixture
def jobs(db_session: Session) -> JobRepository:
    return JobRepository(db_session)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> Tenant:
    tenant = Tenant(client, user_repository, membership_repository, "acme-fashion")
    tenant.on_plan(db_session, PlanTier.BUSINESS)

    return tenant


class Recorder:
    """A handler that says what happened to it, and can be told to fail."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[uuid.UUID] = []

    def run(self, context: JobContext, job: Job) -> None:
        self.calls.append(job.id)

        if self.raises is not None:
            raise self.raises


def _service(
    session: Session,
    jobs: JobRepository,
    handler: Recorder,
    kind: JobKind = JobKind.DELIVER_MESSAGE,
) -> JobService:
    return JobService(session=session, jobs=jobs, handlers={kind: handler})


def _connect(tenant: Tenant) -> None:
    response = tenant.client.post(
        tenant.path("integrations", "whatsapp", "connect"),
        json={
            "phone_number": "+15550001111",
            "external_phone_number_id": "109876543210987",
            "access_token": "a-provider-token",
        },
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text


def _thread(tenant: Tenant) -> str:
    contact = tenant.contact()
    response = tenant.client.post(
        tenant.path("conversations"),
        json={"contact_id": contact},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text

    return str(response.json()["id"])


def _queued_jobs(session: Session, kind: JobKind | None = None) -> list[Job]:
    where = [Job.status == JobStatus.PENDING]

    if kind is not None:
        where.append(Job.kind == kind)

    return list(
        session.scalars(
            select(Job).where(*where).order_by(Job.created_at, Job.id)
        ).all()
    )


# --- claiming ---------------------------------------------------------------


def test_a_due_job_is_claimed_and_marked_running(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    written = jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={"a": 1})

    claimed = jobs.claim(now=datetime.now(UTC))

    assert claimed is not None
    assert claimed.id == written.id
    assert claimed.status is JobStatus.RUNNING
    assert claimed.attempts == 1
    assert claimed.started_at is not None


def test_a_claimed_job_is_not_claimed_again(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    """What survives the commit, and stands in for the lock.

    The lock stops two workers taking the same row in the same instant;
    the status is what stops the second worker a second later.
    """
    jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={})

    assert jobs.claim(now=datetime.now(UTC)) is not None
    assert jobs.claim(now=datetime.now(UTC)) is None


def test_a_job_that_is_not_due_is_left_alone(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    later = datetime.now(UTC) + timedelta(minutes=5)
    jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={}, run_at=later)

    assert jobs.claim(now=datetime.now(UTC)) is None
    assert jobs.claim(now=later) is not None


def test_the_oldest_due_job_goes_first(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    now = datetime.now(UTC)
    second = jobs.enqueue(
        kind=JobKind.DELIVER_MESSAGE,
        payload={},
        run_at=now - timedelta(minutes=1),
        dedupe_key="second",
    )
    first = jobs.enqueue(
        kind=JobKind.DELIVER_MESSAGE,
        payload={},
        run_at=now - timedelta(minutes=5),
        dedupe_key="first",
    )

    claimed = jobs.claim(now=now)

    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.id != second.id


def test_the_same_work_is_never_queued_twice(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    """The deduplication key, which is what makes enqueuing safe to repeat.

    A retried webhook, or two workers planning the same window, must write
    one row between them.
    """
    jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={}, dedupe_key="the-same-work")

    with pytest.raises(IntegrityError):
        jobs.enqueue(
            kind=JobKind.DELIVER_MESSAGE,
            payload={},
            dedupe_key="the-same-work",
        )

    db_session.rollback()


# --- failing ----------------------------------------------------------------


def test_something_outside_saying_no_is_tried_again(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    handler = Recorder(raises=MessagingProviderError("WhatsApp is down"))
    jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={})

    assert _service(db_session, jobs, handler).run_next(
        messaging=FakeMessagingProvider()
    )

    job = db_session.scalars(select(Job)).one()
    assert job.status is JobStatus.PENDING
    assert job.attempts == 1
    assert job.run_at > datetime.now(UTC)
    assert job.last_error is not None


def test_a_bug_is_recorded_and_not_tried_again(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    """Retrying a bug three times produces three of the same stack trace."""
    handler = Recorder(raises=ValueError("this is a bug"))
    jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={})

    _service(db_session, jobs, handler).run_next(messaging=FakeMessagingProvider())

    job = db_session.scalars(select(Job)).one()
    assert job.status is JobStatus.FAILED
    assert job.attempts == 1
    assert "this is a bug" in (job.last_error or "")


def test_a_job_gives_up_when_it_runs_out_of_attempts(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    handler = Recorder(raises=MessagingProviderError("still down"))
    jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={}, max_attempts=2)
    service = _service(db_session, jobs, handler)

    for _ in range(2):
        job = db_session.scalars(select(Job)).one()
        job.run_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.flush()
        service.run_next(messaging=FakeMessagingProvider())

    job = db_session.scalars(select(Job)).one()
    assert job.status is JobStatus.FAILED
    assert job.attempts == 2
    assert job.finished_at is not None


def test_a_kind_with_no_handler_fails_rather_than_looping(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    """One deployment behind on a handler drains what it can, loudly."""
    jobs.enqueue(kind=JobKind.SWEEP_AUTOMATIONS, payload={})

    _service(db_session, jobs, Recorder()).run_next(messaging=FakeMessagingProvider())

    job = db_session.scalars(select(Job)).one()
    assert job.status is JobStatus.FAILED
    assert "No handler" in (job.last_error or "")


def test_the_wait_grows_and_then_stops_growing(db_session: Session) -> None:
    delays = [backoff(attempt) for attempt in range(1, 10)]

    assert delays == sorted(delays)
    assert delays[0] == timedelta(seconds=30)
    assert delays[-1] == timedelta(hours=1)


def test_a_finished_job_says_so(db_session: Session, jobs: JobRepository) -> None:
    handler = Recorder()
    written = jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={})

    _service(db_session, jobs, handler).run_next(messaging=FakeMessagingProvider())

    job = db_session.scalars(select(Job)).one()
    assert handler.calls == [written.id]
    assert job.status is JobStatus.SUCCEEDED
    assert job.finished_at is not None
    assert job.last_error is None


def test_an_empty_queue_says_there_was_nothing(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    assert not _service(db_session, jobs, Recorder()).run_next(
        messaging=FakeMessagingProvider()
    )


# --- abandoned work ---------------------------------------------------------


def test_a_job_a_dead_worker_was_holding_comes_back(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={})
    claimed = jobs.claim(now=datetime.now(UTC))
    assert claimed is not None
    claimed.started_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.flush()

    assert _service(db_session, jobs, Recorder()).reclaim_stalled() == 1

    job = db_session.scalars(select(Job)).one()
    assert job.status is JobStatus.PENDING
    assert job.started_at is None
    # Not wound back: a job that reliably kills its worker should exhaust
    # its attempts like any other failure.
    assert job.attempts == 1


def test_a_job_somebody_is_still_working_on_is_left_alone(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    jobs.enqueue(kind=JobKind.DELIVER_MESSAGE, payload={})
    jobs.claim(now=datetime.now(UTC))

    assert _service(db_session, jobs, Recorder()).reclaim_stalled() == 0


# --- delivering a message ---------------------------------------------------


def test_a_reply_with_nowhere_to_go_is_queued_for_the_worker(
    acme: Tenant,
    db_session: Session,
) -> None:
    """The retry worker this comment has been promising since WhatsApp."""
    conversation = _thread(acme)

    response = acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "We are open until nine."},
        headers=acme.owner_headers,
    )
    assert response.status_code == 201

    queued = _queued_jobs(db_session, JobKind.DELIVER_MESSAGE)
    assert len(queued) == 1
    assert queued[0].payload["message_id"] == response.json()["id"]


def test_a_refused_delivery_is_queued_in_the_same_breath(
    acme: Tenant,
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
) -> None:
    """Three facts about one event, written once.

    The failed status, the notification and the retry are one transaction,
    which is the reason the queue is a table in this database.
    """
    _connect(acme)
    conversation = _thread(acme)
    messaging_provider.fail_with = "WhatsApp is down"

    response = acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "We are open until nine."},
        headers=acme.owner_headers,
    )
    assert response.status_code == 502

    queued = _queued_jobs(db_session, JobKind.DELIVER_MESSAGE)

    assert len(queued) == 1
    # The message is marked failed in the same transaction that queued it,
    # so neither can exist without the other.
    failed = MessageRepository(db_session).get(
        uuid.UUID(acme.workspace_id),
        uuid.UUID(queued[0].payload["message_id"]),
    )
    assert failed is not None
    assert failed.status is MessageStatus.FAILED


def test_the_worker_sends_what_was_queued(
    acme: Tenant,
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
) -> None:
    conversation = _thread(acme)
    sent = acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "We are open until nine."},
        headers=acme.owner_headers,
    ).json()

    # The number arrives after the reply was written, which is exactly the
    # case the queue is for: a business still being set up.
    _connect(acme)
    tick(db_session, messaging=messaging_provider)

    message = MessageRepository(db_session).get(
        uuid.UUID(acme.workspace_id),
        uuid.UUID(sent["id"]),
    )
    assert message is not None
    assert message.status is MessageStatus.SENT
    assert [attempt.text for attempt in messaging_provider.sent] == [
        "We are open until nine."
    ]


def test_a_message_that_has_gone_out_is_not_sent_again(
    acme: Tenant,
    db_session: Session,
    jobs: JobRepository,
    messaging_provider: FakeMessagingProvider,
) -> None:
    """A job can be delivered twice; a customer's phone should not buzz twice.

    The case this guards is real: a worker killed after the provider
    accepted a message but before the row said so leaves a claimed job
    that the stall reclaim hands to somebody else.
    """
    _connect(acme)
    conversation = _thread(acme)
    sent = acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "We are open until nine."},
        headers=acme.owner_headers,
    ).json()
    assert len(messaging_provider.sent) == 1
    # Nothing was queued, because nothing failed.
    assert _queued_jobs(db_session, JobKind.DELIVER_MESSAGE) == []

    # A delivery job for a message that has already gone, which is what a
    # worker killed at the wrong moment leaves behind.
    jobs.enqueue(
        kind=JobKind.DELIVER_MESSAGE,
        workspace_id=uuid.UUID(acme.workspace_id),
        payload={"message_id": sent["id"]},
    )
    tick(db_session, messaging=messaging_provider)

    assert len(messaging_provider.sent) == 1
    assert (
        db_session.scalars(select(Job).where(Job.kind == JobKind.DELIVER_MESSAGE))
        .one()
        .status
        is JobStatus.SUCCEEDED
    )


# --- the schedule -----------------------------------------------------------


def test_planning_writes_one_sweep_for_the_window(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    now = datetime.now(UTC)

    plan(db_session, jobs, now=now)
    plan(db_session, jobs, now=now)

    assert len(_queued_jobs(db_session, JobKind.SWEEP_AUTOMATIONS)) == 1


def test_a_later_window_gets_its_own_sweep(
    db_session: Session,
    jobs: JobRepository,
) -> None:
    now = datetime.now(UTC)

    plan(db_session, jobs, now=now)
    plan(db_session, jobs, now=now + timedelta(hours=1))

    assert len(_queued_jobs(db_session, JobKind.SWEEP_AUTOMATIONS)) == 2


def test_the_sweep_plans_one_job_per_business_that_wants_one(
    acme: Tenant,
    db_session: Session,
    jobs: JobRepository,
    messaging_provider: FakeMessagingProvider,
) -> None:
    response = acme.client.post(
        acme.path("automations"),
        json={"kind": AutomationKind.UNANSWERED_LEAD_FOLLOWUP.value, "definition": {}},
        headers=acme.owner_headers,
    )
    assert response.status_code == 201, response.text

    job = jobs.enqueue(kind=JobKind.SWEEP_AUTOMATIONS, payload={})
    CATALOGUE[JobKind.SWEEP_AUTOMATIONS].run(
        JobContext(
            session=db_session,
            jobs=jobs,
            messaging=messaging_provider,
            now=datetime.now(UTC),
        ),
        job,
    )

    planned = _queued_jobs(db_session, JobKind.RUN_DUE_AUTOMATIONS)
    assert [item.workspace_id for item in planned] == [uuid.UUID(acme.workspace_id)]


def test_a_business_with_nothing_scheduled_is_not_planned_for(
    acme: Tenant,
    db_session: Session,
    jobs: JobRepository,
    messaging_provider: FakeMessagingProvider,
) -> None:
    job = jobs.enqueue(kind=JobKind.SWEEP_AUTOMATIONS, payload={})

    CATALOGUE[JobKind.SWEEP_AUTOMATIONS].run(
        JobContext(
            session=db_session,
            jobs=jobs,
            messaging=messaging_provider,
            now=datetime.now(UTC),
        ),
        job,
    )

    assert _queued_jobs(db_session, JobKind.RUN_DUE_AUTOMATIONS) == []


def test_sweeping_twice_in_one_window_plans_the_work_once(
    acme: Tenant,
    db_session: Session,
    jobs: JobRepository,
    messaging_provider: FakeMessagingProvider,
) -> None:
    acme.client.post(
        acme.path("automations"),
        json={"kind": AutomationKind.UNANSWERED_LEAD_FOLLOWUP.value, "definition": {}},
        headers=acme.owner_headers,
    )
    context = JobContext(
        session=db_session,
        jobs=jobs,
        messaging=messaging_provider,
        now=datetime.now(UTC),
    )
    handler = CATALOGUE[JobKind.SWEEP_AUTOMATIONS]

    handler.run(context, jobs.enqueue(kind=JobKind.SWEEP_AUTOMATIONS, payload={}))
    handler.run(
        context,
        jobs.enqueue(
            kind=JobKind.SWEEP_AUTOMATIONS,
            payload={},
            dedupe_key="a-second-sweep",
        ),
    )

    assert len(_queued_jobs(db_session, JobKind.RUN_DUE_AUTOMATIONS)) == 1
