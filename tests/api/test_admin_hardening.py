"""Phase A8 acceptance: the controls that go in front of what already works.

Six things, and what unites them is that none is a feature. Each takes
something the earlier phases made possible and makes it harder to do by
accident, or easier to notice afterwards:

a second person on the two acts that deserve one; an address allowlist
that is off until somebody turns it on; a shorter window on a console
session (Phase A1, and noted here because this is where hardening is
collected); a page that notices patterns without refusing them; a sweep
that tells a customer their support grant ended; and every platform entry
copied into the log stream operations already watches.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.admin_approval import AdminApproval, ApprovableAction
from app.models.admin_audit_log import AdminAction
from app.models.audit_log import AuditEvent, AuditLog
from app.models.job import Job, JobKind
from app.models.staff_member import StaffRole
from app.models.support_grant import SupportGrant
from app.repositories.job_repository import JobRepository
from app.repositories.support_grant_repository import SupportGrantRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.job_service import JobContext
from app.services.jobs import CATALOGUE
from tests.support.messaging import FakeMessagingProvider
from tests.support.staff import Console, entries, seconded
from tests.support.tenants import Tenant

REASON = "Agreed in the incident channel before doing it"


@pytest.fixture
def owner(client: TestClient, db_session: Session) -> Console:
    return Console(client, db_session, "platform-owner@example.com", StaffRole.OWNER)


@pytest.fixture
def colleague(client: TestClient, db_session: Session) -> Console:
    return Console(client, db_session, "platform-second@example.com", StaffRole.ADMIN)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _raise(console: Console, workspace_id: str) -> str:
    response = console.post(
        "/approvals",
        {
            "action": ApprovableAction.ERASE_WORKSPACE.value,
            "subject": workspace_id,
            "reason": REASON,
        },
    )
    assert response.status_code == 201, response.text

    return str(response.json()["id"])


def _erase(console: Console, tenant: Tenant, approval_id: str) -> Any:
    return console.post(
        f"/workspaces/{tenant.workspace_id}/erase-now",
        {"confirm_slug": "acme-fashion", "approval_id": approval_id},
    )


# --- two people, and not one twice ------------------------------------------


def test_nobody_can_approve_their_own_request(
    owner: Console,
    acme: Tenant,
) -> None:
    """The control rather than a formality.

    An approval you raised and agreed to yourself is a form with extra
    steps.
    """
    approval_id = _raise(owner, acme.workspace_id)

    refused = owner.post(f"/approvals/{approval_id}/approve", {})

    assert refused.status_code == 403
    assert "your own request" in refused.json()["detail"]


def test_the_approver_cannot_also_be_the_performer(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    client: TestClient,
    db_session: Session,
) -> None:
    """ "Two staff members were involved" is not the rule.

    Somebody who approves an erasure and then performs it has been
    through a form, not a two-person process -- so the check is on the
    performer against whoever agreed.
    """
    second_owner = Console(
        client, db_session, "another-owner@example.com", StaffRole.OWNER
    )
    approval_id = _raise(owner, acme.workspace_id)
    second_owner.post(f"/approvals/{approval_id}/approve", {})

    refused = _erase(second_owner, acme, approval_id)

    assert refused.status_code == 403
    assert "approved by you" in refused.json()["detail"]


def test_the_requester_may_perform_it_themselves(
    owner: Console,
    colleague: Console,
    acme: Tenant,
) -> None:
    # Asking a colleague to agree and then doing it yourself is the
    # ordinary shape: one person acting, another having looked.
    approval_id = seconded(
        owner,
        colleague,
        action=ApprovableAction.ERASE_WORKSPACE,
        subject=acme.workspace_id,
    )

    assert _erase(owner, acme, approval_id).status_code == 204


def test_an_approval_is_for_one_workspace_and_not_the_action(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    """A colleague agreeing to erase a test workspace has not agreed to
    erase any of them.
    """
    beta = Tenant(client, user_repository, membership_repository, "beta-goods")
    approval_id = seconded(
        owner,
        colleague,
        action=ApprovableAction.ERASE_WORKSPACE,
        subject=beta.workspace_id,
    )

    refused = _erase(owner, acme, approval_id)

    assert refused.status_code == 403
    assert "something else" in refused.json()["detail"]


def test_an_approval_is_spent_once(
    owner: Console,
    colleague: Console,
    acme: Tenant,
) -> None:
    # Without this a colleague's agreement to erase one workspace would
    # be reusable -- which sounds harmless until the workspace is
    # restored and erased twice.
    approval_id = seconded(
        owner,
        colleague,
        action=ApprovableAction.ERASE_WORKSPACE,
        subject=acme.workspace_id,
    )
    assert _erase(owner, acme, approval_id).status_code == 204

    again = owner.post(
        f"/workspaces/{acme.workspace_id}/erase-now",
        {"confirm_slug": "acme-fashion", "approval_id": approval_id},
    )

    assert again.status_code in {403, 404}


def test_an_expired_approval_is_refused(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # The point of the second person is that they are looking at the same
    # situation. One collected in the morning and spent in the evening is
    # one signature on a decision rather than two.
    approval_id = seconded(
        owner,
        colleague,
        action=ApprovableAction.ERASE_WORKSPACE,
        subject=acme.workspace_id,
    )
    approval = db_session.get(AdminApproval, uuid.UUID(approval_id))
    assert approval is not None
    approval.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    refused = _erase(owner, acme, approval_id)

    assert refused.status_code == 403
    assert "expired" in refused.json()["detail"]


def test_the_slug_is_checked_before_the_approval_is_spent(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # A mistyped erasure should not burn a colleague's agreement.
    approval_id = seconded(
        owner,
        colleague,
        action=ApprovableAction.ERASE_WORKSPACE,
        subject=acme.workspace_id,
    )

    mistyped = owner.post(
        f"/workspaces/{acme.workspace_id}/erase-now",
        {"confirm_slug": "acme", "approval_id": approval_id},
    )

    assert mistyped.status_code == 422
    # And the approval is still good.
    assert _erase(owner, acme, approval_id).status_code == 204


def test_all_four_moments_of_an_approval_are_recorded(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # A control whose own history were thinner than the act it guards
    # would be decoration.
    approval_id = seconded(
        owner,
        colleague,
        action=ApprovableAction.ERASE_WORKSPACE,
        subject=acme.workspace_id,
    )
    _erase(owner, acme, approval_id)
    owner.get("/approvals")

    assert len(entries(db_session, AdminAction.APPROVAL_REQUESTED)) == 1
    assert len(entries(db_session, AdminAction.APPROVAL_GRANTED)) == 1
    assert len(entries(db_session, AdminAction.APPROVAL_SPENT)) == 1
    assert len(entries(db_session, AdminAction.APPROVALS_READ)) == 1


def test_the_approval_list_names_both_people(
    owner: Console,
    colleague: Console,
    acme: Tenant,
) -> None:
    seconded(
        owner,
        colleague,
        action=ApprovableAction.ERASE_WORKSPACE,
        subject=acme.workspace_id,
    )

    listed = owner.get("/approvals").json()

    assert listed["total"] == 1
    assert listed["items"][0]["requested_by"] == "platform-owner@example.com"
    assert listed["items"][0]["approved_by"] == "platform-second@example.com"
    assert listed["items"][0]["usable"] is True


# --- the allowlist ----------------------------------------------------------


def test_the_allowlist_is_off_until_somebody_turns_it_on(
    owner: Console,
) -> None:
    # A deployment shipping with an allowlist would lock its own operator
    # out on the first day.
    assert get_settings().admin_ip_allowlist == []
    assert owner.get("/me").status_code == 200


def test_an_address_off_the_list_is_refused(
    owner: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checked before the staff row is looked up.

    A stolen session on the wrong network learns nothing about whether
    the account it holds is staff.
    """
    # The cached instance, because that is what the dependency reads --
    # and monkeypatch puts it back, so the next test is not locked out.
    monkeypatch.setattr(get_settings(), "admin_ip_allowlist", ["198.51.100.7"])

    refused = owner.get("/me")

    assert refused.status_code == 403
    assert refused.json()["code"] == "address_not_allowed"


# --- a lapsed grant is closed, and the customer told ------------------------


def test_the_sweep_closes_a_lapsed_grant_and_tells_the_customer(
    client: TestClient,
    db_session: Session,
    acme: Tenant,
) -> None:
    """The gap Phase A3 left.

    An expired grant already stops working -- it fails the lookup, with
    nothing having to run. What it does not do is tell the customer it
    ended, so their log would show access granted and never show it
    close.
    """
    support = Console(client, db_session, "support@example.com", StaffRole.SUPPORT)
    granted = support.post(
        f"/workspaces/{acme.workspace_id}/support-access",
        {"reason": "Investigating the delivery failure they reported"},
    )
    assert granted.status_code == 201

    grant = db_session.scalar(select(SupportGrant))
    assert grant is not None
    grant.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    assert SupportGrantRepository(db_session).lapsed(datetime.now(UTC)) == [grant]

    _run_the_sweep(db_session)

    db_session.expire_all()
    grant = db_session.scalar(select(SupportGrant))
    assert grant is not None
    assert grant.revoked_at is not None

    ended = db_session.scalars(
        select(AuditLog).where(AuditLog.event == AuditEvent.SUPPORT_ACCESS_ENDED)
    ).all()

    assert len(ended) == 1
    assert ended[0].meta["by_staff"] == "support@example.com"
    assert ended[0].meta["ended"] == "expired"


def test_the_sweep_is_safe_to_run_twice(
    client: TestClient,
    db_session: Session,
    acme: Tenant,
) -> None:
    # A grant stamped by the first pass is not lapsed any more, so the
    # second finds nothing.
    support = Console(client, db_session, "support@example.com", StaffRole.SUPPORT)
    support.post(
        f"/workspaces/{acme.workspace_id}/support-access",
        {"reason": "Investigating the delivery failure they reported"},
    )
    grant = db_session.scalar(select(SupportGrant))
    assert grant is not None
    grant.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    _run_the_sweep(db_session)
    _run_the_sweep(db_session)

    ended = db_session.scalars(
        select(AuditLog).where(AuditLog.event == AuditEvent.SUPPORT_ACCESS_ENDED)
    ).all()

    assert len(ended) == 1


def _run_the_sweep(session: Session) -> None:
    """The handler, on the test's own session.

    Called directly rather than through the worker loop: what is under
    test is what the sweep does, and the loop that plans it has its own
    suite.
    """
    handler = CATALOGUE[JobKind.SWEEP_SUPPORT_GRANTS]
    handler.run(
        JobContext(
            session=session,
            jobs=JobRepository(session),
            # Never touched: this sweep sends nothing. Passed because the
            # context is assembled whole.
            messaging=FakeMessagingProvider(),
            now=datetime.now(UTC),
        ),
        Job(kind=JobKind.SWEEP_SUPPORT_GRANTS, payload={}),
    )


# --- noticing without refusing ----------------------------------------------


def test_the_alerts_page_counts_customers_read_not_requests(
    owner: Console,
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    """Somebody refreshing one account's page is working.

    Somebody opening forty accounts is either running a migration or
    going through the customer list, and only the second is a question.
    """
    beta = Tenant(client, user_repository, membership_repository, "beta-goods")

    owner.get(f"/workspaces/{acme.workspace_id}")
    owner.get(f"/workspaces/{acme.workspace_id}")
    owner.get(f"/workspaces/{acme.workspace_id}")
    owner.get(f"/workspaces/{beta.workspace_id}")

    body = owner.get("/alerts").json()
    mine = [
        reader
        for reader in body["busiest_readers"]
        if reader["email"] == "platform-owner@example.com"
    ]

    # Two workspaces, four requests.
    assert mine[0]["workspaces_read"] == 2


def test_the_alerts_page_refuses_nothing(owner: Console, acme: Tenant) -> None:
    # A control that refused these would be worked around within a week
    # by whoever was on call.
    for _ in range(5):
        assert owner.get(f"/workspaces/{acme.workspace_id}").status_code == 200

    body = owner.get("/alerts").json()

    assert body["over_threshold"] == []
    assert body["threshold"] == get_settings().admin_workspace_reads_per_hour


def test_searching_the_workspace_list_is_not_reading_a_customer(
    owner: Console,
    acme: Tenant,
) -> None:
    # Searching touches every business by definition, and counting it
    # would put whoever opened the console at the top of this page every
    # time.
    owner.get("/workspaces")

    body = owner.get("/alerts").json()

    assert body["busiest_readers"] == []


# --- into the log stream ----------------------------------------------------


def test_every_platform_entry_is_written_to_the_log_too(
    owner: Console,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The plan's "load /admin/audit into whatever log store operations
    already uses", done by writing it there.

    The row is the record and the line is a copy. What the copy buys is
    that "who touched this workspace on Tuesday" can be asked in the same
    place as every other question that day.
    """
    with caplog.at_level(logging.INFO, logger="app.services.admin_audit_service"):
        owner.get("/me")

    lines = [record for record in caplog.records if hasattr(record, "admin_action")]

    assert lines
    assert lines[0].admin_action == AdminAction.CONSOLE_OPENED.value
    assert lines[0].admin_actor == "platform-owner@example.com"


def test_the_log_line_carries_no_metadata(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # `meta` carries whatever a caller put in it, and a log line is
    # exactly where an address or a reason gets copied, shipped and kept
    # longest.
    with caplog.at_level(logging.INFO, logger="app.services.admin_audit_service"):
        seconded(
            owner,
            colleague,
            action=ApprovableAction.ERASE_WORKSPACE,
            subject=acme.workspace_id,
        )

    for record in caplog.records:
        assert REASON not in record.getMessage()
        assert not hasattr(record, "admin_meta")
