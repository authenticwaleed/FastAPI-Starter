"""Phase A6 acceptance: why did this not work.

The phase that decides whether anybody can run this product at three in
the morning. Most of it is ordinary -- a queue with filters, a list of
refusals, a health page -- and two things in it are not, so they are
where the tests are.

A job payload can carry a customer's message text, so it is redacted by
kind on a safe-list rather than dumped: an operations console is not a
licence to read messages. And a retry must not race the worker already
holding the row.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAction
from app.models.job import Job, JobKind, JobStatus
from app.models.staff_member import StaffRole
from app.models.webhook_failure import WebhookRefusal
from app.repositories.job_repository import JobRepository
from app.repositories.user_repository import UserRepository
from app.repositories.webhook_failure_repository import WebhookFailureRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.admin_operations_service import REDACTED, visible_payload
from tests.support.staff import Console, entries
from tests.support.tenants import Tenant


@pytest.fixture
def admin(client: TestClient, db_session: Session) -> Console:
    return Console(client, db_session, "platform-admin@example.com", StaffRole.ADMIN)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _a_failed_delivery(session: Session, tenant: Tenant) -> Job:
    """One `deliver_message` job that did not go, with an error on it."""
    jobs = JobRepository(session)
    job = jobs.enqueue(
        kind=JobKind.DELIVER_MESSAGE,
        workspace_id=uuid.UUID(tenant.workspace_id),
        payload={"message_id": str(uuid.uuid4())},
        run_at=datetime.now(UTC),
    )
    job.status = JobStatus.FAILED
    job.attempts = 3
    job.last_error = "WhatsApp refused the message: recipient not opted in"
    session.flush()

    return job


# --- the queue --------------------------------------------------------------


def test_a_failed_delivery_is_findable_by_workspace_and_by_kind(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The acceptance criterion, and the query the screen exists for.

    It turns "their message never arrived" into a row with a reason on
    it, without anybody opening a database console.
    """
    _a_failed_delivery(db_session, acme)

    found = admin.get(
        "/jobs",
        kind=JobKind.DELIVER_MESSAGE.value,
        status=JobStatus.FAILED.value,
        workspace_id=acme.workspace_id,
    ).json()

    assert found["total"] == 1
    assert "recipient not opted in" in found["items"][0]["last_error"]
    assert found["items"][0]["attempts"] == 3


def test_retrying_moves_a_job_back_to_pending(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # And it is picked up: `run_at` is now and the attempts are forgiven,
    # which is exactly what the worker's claim query looks for.
    job = _a_failed_delivery(db_session, acme)

    body = admin.post(f"/jobs/{job.id}/retry", {}).json()

    assert body["status"] == JobStatus.PENDING.value
    assert body["attempts"] == 0
    assert body["last_error"] is None

    claimed = JobRepository(db_session).claim(now=datetime.now(UTC))
    assert claimed is not None
    assert claimed.id == job.id


def test_a_running_job_is_not_retried(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """What respecting the dedupe key comes to in practice.

    The worker holding a running row does not check back, so moving it to
    pending would let a second worker claim the same work and race the
    first -- two deliveries of one message.
    """
    job = _a_failed_delivery(db_session, acme)
    job.status = JobStatus.RUNNING
    db_session.flush()

    refused = admin.post(f"/jobs/{job.id}/retry", {})

    assert refused.status_code == 409
    assert refused.json()["code"] == "job_not_retryable"


def test_retrying_leaves_the_dedupe_key_alone(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # The unique index on that column is what stops a second row for the
    # same work existing. Clearing it here would let the next sweep
    # enqueue a twin that races this one.
    jobs = JobRepository(db_session)
    job = jobs.enqueue(
        kind=JobKind.SWEEP_AUTOMATIONS,
        workspace_id=None,
        payload={"window": "2026-09-02T12:00:00Z"},
        run_at=datetime.now(UTC),
        dedupe_key="sweep_automations:2026-09-02T12:00",
    )
    job.status = JobStatus.FAILED
    db_session.flush()

    body = admin.post(f"/jobs/{job.id}/retry", {}).json()

    assert body["dedupe_key"] == "sweep_automations:2026-09-02T12:00"


def test_a_cancelled_job_is_told_from_a_failed_one(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # A failure is something to investigate; a cancellation is something
    # somebody already decided about.
    jobs = JobRepository(db_session)
    job = jobs.enqueue(
        kind=JobKind.DELIVER_MESSAGE,
        workspace_id=uuid.UUID(acme.workspace_id),
        payload={"message_id": str(uuid.uuid4())},
        run_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.flush()

    body = admin.post(f"/jobs/{job.id}/cancel", {}).json()

    assert body["status"] == JobStatus.CANCELLED.value
    assert body["finished_at"] is not None
    # And the row is kept, so the decision can be found afterwards.
    assert admin.get("/jobs", status=JobStatus.CANCELLED.value).json()["total"] == 1


def test_a_job_that_already_succeeded_is_not_retried(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    job = _a_failed_delivery(db_session, acme)
    job.status = JobStatus.SUCCEEDED
    db_session.flush()

    assert admin.post(f"/jobs/{job.id}/retry", {}).status_code == 409


def test_an_unknown_job_is_a_404(admin: Console) -> None:
    assert admin.get(f"/jobs/{uuid.uuid4()}").status_code == 404


# --- what a payload is allowed to show --------------------------------------


def test_a_payload_is_redacted_by_kind_on_a_safe_list(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The rule that keeps an operations console from becoming a reader.

    A deny-list would leak a new field until somebody noticed. This hides
    anything not named for the kind, so the day a message's text lands in
    a `deliver_message` payload to save a lookup, it stays out.
    """
    jobs = JobRepository(db_session)
    message_id = str(uuid.uuid4())
    job = jobs.enqueue(
        kind=JobKind.DELIVER_MESSAGE,
        workspace_id=uuid.UUID(acme.workspace_id),
        payload={
            "message_id": message_id,
            # The field somebody adds next year to save a lookup.
            "text": "Hello, is my order on its way?",
        },
        run_at=datetime.now(UTC),
    )
    db_session.flush()

    response = admin.get(f"/jobs/{job.id}")
    body = response.json()

    assert body["payload"]["message_id"] == message_id
    assert body["payload"]["text"] == REDACTED
    assert "Hello, is my order" not in response.text


def test_an_unknown_kind_shows_nothing_at_all() -> None:
    # The safe end of the failure: a new job type appears in the console
    # with its payload hidden, and somebody adds it to the list on
    # purpose.
    job = Job(kind=JobKind.DELIVER_MESSAGE, payload={"anything": "at all"})
    job.kind = "a_kind_nobody_listed"  # type: ignore[assignment]

    assert visible_payload(job) == {"anything": REDACTED}


def test_a_summary_carries_no_payload_at_all(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # A list is the screen somebody leaves open. Fetching one job to see
    # its payload is a deliberate act, with its own audit entry.
    _a_failed_delivery(db_session, acme)

    listed = admin.get("/jobs").json()

    assert "payload" not in listed["items"][0]


# --- the refusals -----------------------------------------------------------


def test_a_refused_delivery_is_recorded_and_readable(
    admin: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    """The one failure that otherwise reaches nobody.

    The provider gets a status code, the sender is a machine, and the
    customer whose secret was mistyped notices days later that their
    orders stopped arriving.
    """
    forged = client.post(
        "/api/v1/webhooks/whatsapp",
        content=b'{"entry": []}',
        headers={
            "X-Hub-Signature-256": "sha256=not-a-real-signature",
            "Content-Type": "application/json",
        },
    )

    assert forged.status_code == 403

    listed = admin.get("/webhooks/failures").json()

    assert listed["total"] == 1
    assert listed["items"][0]["provider"] == "whatsapp"
    assert listed["items"][0]["reason"] == WebhookRefusal.BAD_SIGNATURE.value
    assert listed["items"][0]["path"] == "/api/v1/webhooks/whatsapp"


def test_no_refused_body_is_ever_stored(
    admin: Console,
    client: TestClient,
) -> None:
    # A delivery that failed to verify came from somebody unproven, so
    # keeping what they sent would be keeping whatever a stranger chose
    # to post at this endpoint.
    secret = "a-string-a-stranger-posted"
    client.post(
        "/api/v1/webhooks/whatsapp",
        content=f'{{"entry": "{secret}"}}'.encode(),
        headers={
            "X-Hub-Signature-256": "sha256=not-a-real-signature",
            "Content-Type": "application/json",
        },
    )

    assert secret not in admin.get("/webhooks/failures").text


def test_refusals_narrow_by_provider_and_reason(
    admin: Console,
    db_session: Session,
) -> None:
    # A run of bad signatures from one address is somebody probing; the
    # same reason from one provider, steadily, is a customer with the
    # wrong secret. They look identical unfiltered.
    failures = WebhookFailureRepository(db_session)
    failures.record(
        provider="shopify",
        reason=WebhookRefusal.BAD_SIGNATURE,
        path="/api/v1/webhooks/shopify",
        ip_address="203.0.113.9",
    )
    failures.record(
        provider="billing",
        reason=WebhookRefusal.MALFORMED,
        path="/api/v1/webhooks/billing",
        ip_address="203.0.113.9",
    )
    db_session.flush()

    assert admin.get("/webhooks/failures", provider="shopify").json()["total"] == 1
    assert (
        admin.get("/webhooks/failures", reason=WebhookRefusal.MALFORMED.value).json()[
            "total"
        ]
        == 1
    )


# --- is anything wrong ------------------------------------------------------


def test_health_says_how_deep_the_queue_is_and_how_old(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The two numbers together, because either alone says nothing.

    Two hundred draining in a minute is a busy afternoon; three where the
    oldest has waited an hour is a worker that has stopped.
    """
    jobs = JobRepository(db_session)
    jobs.enqueue(
        kind=JobKind.DELIVER_MESSAGE,
        workspace_id=uuid.UUID(acme.workspace_id),
        payload={"message_id": str(uuid.uuid4())},
        run_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    db_session.flush()

    body = admin.get("/health").json()

    assert body["database"] is True
    assert body["queue"]["depth"] == 1
    assert body["queue"]["oldest_pending_seconds"] > 1500


def test_an_empty_queue_has_no_oldest_rather_than_zero(admin: Console) -> None:
    # Zero would read as "something is waiting and it just arrived".
    body = admin.get("/health").json()

    assert body["queue"]["depth"] == 0
    assert body["queue"]["oldest_pending_seconds"] is None


def test_health_reports_configuration_rather_than_dialling_anybody(
    admin: Console,
) -> None:
    """Deliberately short of a live check.

    A page that called Meta, Stripe and two storefronts on every load
    would be slow, rate limited by somebody else's API, and would report
    an outage every time one had a slow minute. What it catches instead
    is the failure that actually bites: a deployment missing a key, which
    otherwise surfaces at the first customer who needs it.
    """
    body = admin.get("/health").json()

    assert set(body["integrations"]) == {
        "whatsapp",
        "billing",
        "embeddings",
        "assistant",
        "email",
        "encryption",
    }
    # The suite configures these, so they read as present.
    assert body["integrations"]["whatsapp"] is True
    assert body["integrations"]["encryption"] is True


def test_the_operations_console_is_admin_only(
    client: TestClient,
    db_session: Session,
) -> None:
    # A retry re-sends somebody's message and a cancellation stops one
    # being sent at all. Neither is the rank that answers tickets.
    console = Console(client, db_session, "support@example.com", StaffRole.SUPPORT)

    assert console.get("/jobs").status_code == 403
    assert console.get("/health").status_code == 403
    assert console.get("/webhooks/failures").status_code == 403


def test_every_operations_read_is_recorded(
    admin: Console,
    db_session: Session,
) -> None:
    # A job payload names a workspace, so reading the queue is reading
    # which customers had trouble.
    admin.get("/jobs")
    admin.get("/health")

    assert len(entries(db_session, AdminAction.JOBS_SEARCHED)) == 1
    assert len(entries(db_session, AdminAction.HEALTH_READ)) == 1
