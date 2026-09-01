"""Phase 30 acceptance: the checklist, where it is code rather than a runbook.

Most of the list was settled by earlier phases -- credentials are
encrypted, webhooks are signed, CORS is named, tokens expire, uploads are
capped, tenants are isolated -- and each of those has its own suite. What
is here is what this phase added: what a browser is told, what a rotated
key can still read, and the workflow that actually destroys a customer's
data on the date they were given.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.encryption import decrypt, encrypt, generate_key
from app.main import create_app
from app.models.audit_log import AuditEvent, AuditLog
from app.models.contact import Contact
from app.models.job import Job, JobKind
from app.models.workspace import Workspace, WorkspaceStatus
from app.repositories.job_repository import JobRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.job_service import JobContext
from app.services.jobs import CATALOGUE
from app.worker import tick
from tests.support.messaging import FakeMessagingProvider
from tests.support.tenants import Tenant


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _workspace(session: Session, workspace_id: str) -> Workspace | None:
    return session.get(Workspace, uuid.UUID(workspace_id))


def _close(tenant: Tenant) -> None:
    response = tenant.client.delete(tenant.path(), headers=tenant.owner_headers)
    assert response.status_code in (200, 204), response.text


# --- what a browser is told -------------------------------------------------


@pytest.mark.parametrize(
    ("header", "value"),
    [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        ("content-security-policy", "default-src 'none'; frame-ancestors 'none'"),
    ],
)
def test_every_response_says_what_may_be_done_with_it(
    client: TestClient,
    header: str,
    value: str,
) -> None:
    assert client.get("/api/v1/health").headers[header] == value


def test_a_refused_request_is_told_the_same_things(client: TestClient) -> None:
    """A browser should be told not to sniff a 401 as readily as a 200."""
    response = client.get("/api/v1/account")

    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"


def test_development_does_not_pin_a_browser_to_https(client: TestClient) -> None:
    """A browser told to upgrade localhost for two years cannot easily be
    untold."""
    assert "strict-transport-security" not in client.get("/api/v1/health").headers


def test_production_pins_it_for_two_years() -> None:
    settings = get_settings().model_copy(
        update={
            "environment": "production",
            "debug": False,
            "cors_origins": ["https://app.example.com"],
            "allowed_hosts": ["app.example.com"],
            "log_format": "json",
        }
    )

    with TestClient(
        create_app(settings),
        base_url="http://app.example.com",
    ) as production:
        header = production.get("/api/v1/health").headers["strict-transport-security"]

    assert "max-age=63072000" in header
    assert "includeSubDomains" in header


# --- rotating the key -------------------------------------------------------


def test_a_value_written_under_the_previous_key_still_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the second slot.

    Without it, changing the key is a deployment in which every stored
    provider token stops decrypting at once -- so the key is never
    changed, and a key nobody can rotate lives for the life of the product.
    """
    from app.core import encryption

    old = generate_key()
    new = generate_key()

    def _with(current: str, previous: str | None) -> None:
        encryption._cipher.cache_clear()
        # SecretStr, because that is what the field holds and the cipher
        # calls get_secret_value on it.
        replacement = get_settings().model_copy(
            update={
                "encryption_key": SecretStr(current),
                "encryption_key_previous": (
                    SecretStr(previous) if previous is not None else None
                ),
            }
        )
        monkeypatch.setattr(encryption, "get_settings", lambda: replacement)

    _with(old, None)
    written_before = encrypt("a-provider-token")

    _with(new, old)
    assert decrypt(written_before) == "a-provider-token"

    # And anything written now uses the new key, so dropping the old one
    # is the last step rather than a second outage.
    written_after = encrypt("a-newer-token")

    _with(new, None)
    assert decrypt(written_after) == "a-newer-token"

    encryption._cipher.cache_clear()


# --- destroying a customer's data -------------------------------------------


def test_closing_a_workspace_sets_a_date_rather_than_deleting_it(
    acme: Tenant,
    db_session: Session,
) -> None:
    acme.contact()

    _close(acme)

    workspace = _workspace(db_session, acme.workspace_id)
    assert workspace is not None
    assert workspace.status is WorkspaceStatus.CANCELLED
    assert workspace.erase_after is not None
    assert workspace.erase_after > datetime.now(UTC) + timedelta(days=29)


def test_the_date_is_recorded_where_it_outlives_the_workspace(
    acme: Tenant,
    db_session: Session,
) -> None:
    """The audit entry is the only thing that will still say it was asked
    for."""
    _close(acme)

    entry = db_session.scalars(
        select(AuditLog).where(AuditLog.event == AuditEvent.WORKSPACE_CLOSED)
    ).one()

    assert entry.workspace_id == uuid.UUID(acme.workspace_id)
    assert entry.actor_email == "owner-acme-fashion@example.com"
    assert entry.meta["erase_after"]


def test_an_open_workspace_is_never_due(
    acme: Tenant,
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
) -> None:
    acme.contact()

    tick(db_session, messaging=messaging_provider)

    assert _workspace(db_session, acme.workspace_id) is not None


def test_a_closed_workspace_is_left_alone_until_its_date(
    acme: Tenant,
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
) -> None:
    """The grace period, which is the half that makes this survivable."""
    _close(acme)

    for _ in range(2):
        tick(db_session, messaging=messaging_provider)

    assert _workspace(db_session, acme.workspace_id) is not None


def test_the_worker_destroys_it_once_the_date_has_passed(
    acme: Tenant,
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
) -> None:
    workspace_id = uuid.UUID(acme.workspace_id)
    acme.contact()
    _close(acme)

    workspace = _workspace(db_session, acme.workspace_id)
    assert workspace is not None
    workspace.erase_after = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    # Two passes: the first sweep queues the erasure, the second runs it.
    for _ in range(2):
        tick(db_session, messaging=messaging_provider)

    assert _workspace(db_session, acme.workspace_id) is None
    # And everything that hung off it, by the cascade the tenant boundary
    # was built with rather than by a second list kept in step by hand.
    assert (
        db_session.scalars(
            select(Contact).where(Contact.workspace_id == workspace_id)
        ).all()
        == []
    )


def test_changing_your_mind_before_the_date_stops_it(
    acme: Tenant,
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
) -> None:
    """The job checks the date again rather than trusting why it was queued.

    A job can sit in the queue through a restart, a reclaim, and somebody
    changing their mind -- and the one job here that cannot be undone is
    the one that must not act on a stale reason.
    """
    _close(acme)
    workspace = _workspace(db_session, acme.workspace_id)
    assert workspace is not None

    # Queued directly rather than through a sweep, because a single pass
    # of the worker both plans and drains -- and what this test is about
    # is the gap between those two, which a real deployment has whenever
    # the queue is busy.
    JobRepository(db_session).enqueue(
        kind=JobKind.ERASE_WORKSPACE,
        payload={"workspace_id": acme.workspace_id},
    )
    db_session.flush()

    # Reopened between the job being queued and being run.
    workspace.status = WorkspaceStatus.ACTIVE
    workspace.erase_after = None
    db_session.flush()

    tick(db_session, messaging=messaging_provider)

    assert _workspace(db_session, acme.workspace_id) is not None


def test_one_business_closing_never_takes_another_with_it(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
) -> None:
    rival = Tenant(client, user_repository, membership_repository, "rival-store")
    rival.contact()
    acme.contact()
    _close(acme)

    workspace = _workspace(db_session, acme.workspace_id)
    assert workspace is not None
    workspace.erase_after = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    for _ in range(2):
        tick(db_session, messaging=messaging_provider)

    assert _workspace(db_session, acme.workspace_id) is None
    assert _workspace(db_session, rival.workspace_id) is not None
    assert db_session.scalars(
        select(Contact).where(Contact.workspace_id == uuid.UUID(rival.workspace_id))
    ).all()


def test_erasure_is_queued_once_however_many_sweeps_run(
    acme: Tenant,
    db_session: Session,
    messaging_provider: FakeMessagingProvider,
) -> None:
    """One erasure of a business, ever -- the key carries no window."""
    _close(acme)
    workspace = _workspace(db_session, acme.workspace_id)
    assert workspace is not None
    workspace.erase_after = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    jobs = JobRepository(db_session)
    sweep = CATALOGUE[JobKind.SWEEP_ERASURES]
    context = JobContext(
        session=db_session,
        jobs=jobs,
        messaging=messaging_provider,
        now=datetime.now(UTC),
    )

    for _ in range(3):
        sweep.run(context, jobs.enqueue(kind=JobKind.SWEEP_ERASURES, payload={}))

    queued = db_session.scalars(
        select(Job).where(Job.kind == JobKind.ERASE_WORKSPACE)
    ).all()

    assert len(queued) == 1
    # Named in the payload, because the column that would name it cascades
    # from the workspace this job exists to delete.
    assert queued[0].payload["workspace_id"] == acme.workspace_id
    assert queued[0].workspace_id is None
