"""Phase A1 acceptance: the log that outlives what it is about.

Three things, and the third is why this table exists at all.

Every route on the platform surface writes an entry, reads included --
the case table below is checked against the router itself, so a route
added without one fails here rather than going quietly unaudited.

The entry survives its actor, which is what stops a staff member erasing
themselves from the record by closing their account.

And the entry survives its *subject*. When a workspace is finally erased,
its own audit log goes with it, correctly: the customer asked to be
forgotten. What must not go with it is the record that a staff member
read that workspace two days beforehand -- and a cascade would delete
exactly that row at exactly that moment.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAction, AdminAuditLog
from app.models.job import JobKind
from app.models.staff_member import StaffRole
from app.models.subscription import BillingProviderName
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.admin_audit_log_repository import AdminAuditLogRepository
from app.repositories.job_repository import JobRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.admin_audit_service import AdminActor, AdminAuditService
from tests.support.staff import ADMIN, Console, a_colleague, entries, operations
from tests.support.tenants import Tenant, sign_up


@pytest.fixture
def owner(client: TestClient, db_session: Session) -> Console:
    return Console(client, db_session, "platform-owner@example.com", StaffRole.OWNER)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    """A business for the console's routes to be pointed at.

    The read-only routes need a real workspace, because every one of them
    proves it exists before recording that it was read -- which is what
    stops the log filling with entries about ids that never existed.
    """
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _a_job(session: Session) -> str:
    """One pending job, so cancel and retry have something to act on.

    Pending rather than failed, and in that order in the table below:
    cancel refuses anything not waiting, and retry refuses anything
    running or succeeded -- so cancelling first leaves exactly the state
    the retry after it accepts.
    """
    job = JobRepository(session).enqueue(
        kind=JobKind.DELIVER_MESSAGE,
        workspace_id=None,
        payload={"message_id": str(uuid.uuid4())},
        run_at=datetime.now(UTC),
    )
    session.flush()

    return str(job.id)


def _a_billing_delivery(session: Session) -> str:
    """One stored delivery, so the replay route has something to re-apply.

    Recorded through the repository rather than by walking a checkout: a
    replay is about a row in `billing_events`, and how it got there is
    the payment webhook's own test.
    """
    event = SubscriptionRepository(session).record_event(
        provider=BillingProviderName.STRIPE,
        provider_event_id="evt_for_the_audit_case",
        event_type="customer.subscription.updated",
    )
    session.flush()

    return str(event.id)


def _a_conversation(tenant: Tenant) -> str:
    """One real thread, so the messages route has something to open."""
    response = tenant.client.post(
        tenant.path("conversations"),
        json={"contact_id": tenant.contact()},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text

    return str(response.json()["id"])


def _calls(
    console: Console,
    colleague: int,
    workspace_id: str,
    conversation_id: str,
    slug: str,
    billing_event_id: str,
    job_id: str,
) -> dict[tuple[str, str], tuple[Callable[[], Any], AdminAction]]:
    """One valid call per published operation, and what it should record.

    Written by hand, because only a person knows what a valid call to a
    route looks like -- and checked against the router by the test below,
    so the hand-written part cannot fall behind the published one.

    In order: granting has to happen before there is anybody to promote
    or revoke.
    """
    return {
        ("GET", f"{ADMIN}/me"): (
            lambda: console.get("/me"),
            AdminAction.CONSOLE_OPENED,
        ),
        ("GET", f"{ADMIN}/staff"): (
            lambda: console.get("/staff"),
            AdminAction.STAFF_LISTED,
        ),
        ("POST", f"{ADMIN}/staff"): (
            lambda: console.post(
                "/staff",
                {"user_id": colleague, "role": StaffRole.SUPPORT.value},
            ),
            AdminAction.STAFF_GRANTED,
        ),
        ("PATCH", f"{ADMIN}/staff/{{user_id}}"): (
            lambda: console.patch(
                f"/staff/{colleague}",
                {"role": StaffRole.ADMIN.value},
            ),
            AdminAction.STAFF_ROLE_CHANGED,
        ),
        ("DELETE", f"{ADMIN}/staff/{{user_id}}"): (
            lambda: console.delete(f"/staff/{colleague}"),
            AdminAction.STAFF_REVOKED,
        ),
        ("GET", f"{ADMIN}/audit"): (
            lambda: console.get("/audit"),
            AdminAction.AUDIT_READ,
        ),
        # The read-only console. Nine reads, and every one of them
        # recorded -- which is the rule this surface is built on and the
        # thing a list of only writes would fail to answer.
        ("GET", f"{ADMIN}/workspaces"): (
            lambda: console.get("/workspaces"),
            AdminAction.WORKSPACES_SEARCHED,
        ),
        ("GET", f"{ADMIN}/workspaces/{{workspace_id}}"): (
            lambda: console.get(f"/workspaces/{workspace_id}"),
            AdminAction.WORKSPACE_READ,
        ),
        ("GET", f"{ADMIN}/workspaces/{{workspace_id}}/members"): (
            lambda: console.get(f"/workspaces/{workspace_id}/members"),
            AdminAction.WORKSPACE_MEMBERS_READ,
        ),
        ("GET", f"{ADMIN}/workspaces/{{workspace_id}}/subscription"): (
            lambda: console.get(f"/workspaces/{workspace_id}/subscription"),
            AdminAction.WORKSPACE_SUBSCRIPTION_READ,
        ),
        ("GET", f"{ADMIN}/workspaces/{{workspace_id}}/usage"): (
            lambda: console.get(f"/workspaces/{workspace_id}/usage"),
            AdminAction.WORKSPACE_USAGE_READ,
        ),
        ("GET", f"{ADMIN}/workspaces/{{workspace_id}}/integrations"): (
            lambda: console.get(f"/workspaces/{workspace_id}/integrations"),
            AdminAction.WORKSPACE_INTEGRATIONS_READ,
        ),
        ("GET", f"{ADMIN}/workspaces/{{workspace_id}}/audit"): (
            lambda: console.get(f"/workspaces/{workspace_id}/audit"),
            AdminAction.WORKSPACE_AUDIT_READ,
        ),
        ("GET", f"{ADMIN}/users"): (
            lambda: console.get("/users"),
            AdminAction.USERS_SEARCHED,
        ),
        ("GET", f"{ADMIN}/users/{{user_id}}"): (
            lambda: console.get(f"/users/{colleague}"),
            AdminAction.USER_READ,
        ),
        # Support access, and the two reads it opens. In this order
        # because the reads need the grant the first of them asks for,
        # and the last of them ends it.
        ("POST", f"{ADMIN}/workspaces/{{workspace_id}}/support-access"): (
            lambda: console.post(
                f"/workspaces/{workspace_id}/support-access",
                {"reason": "Investigating a reported delivery failure"},
            ),
            AdminAction.SUPPORT_ACCESS_GRANTED,
        ),
        ("GET", f"{ADMIN}/workspaces/{{workspace_id}}/conversations"): (
            lambda: console.get(f"/workspaces/{workspace_id}/conversations"),
            AdminAction.CONVERSATIONS_READ,
        ),
        (
            "GET",
            f"{ADMIN}/workspaces/{{workspace_id}}/conversations"
            "/{conversation_id}/messages",
        ): (
            lambda: console.get(
                f"/workspaces/{workspace_id}/conversations/{conversation_id}/messages"
            ),
            AdminAction.MESSAGES_READ,
        ),
        ("GET", f"{ADMIN}/workspaces/{{workspace_id}}/support-access"): (
            lambda: console.get(f"/workspaces/{workspace_id}/support-access"),
            AdminAction.SUPPORT_ACCESS_LISTED,
        ),
        ("DELETE", f"{ADMIN}/workspaces/{{workspace_id}}/support-access"): (
            lambda: console.delete(f"/workspaces/{workspace_id}/support-access"),
            AdminAction.SUPPORT_ACCESS_REVOKED,
        ),
        # Lifecycle. In an order that leaves the workspace usable for the
        # ones after it, and with the erasure last -- because after it
        # there is no workspace for anything else to name.
        ("POST", f"{ADMIN}/workspaces/{{workspace_id}}/suspend"): (
            lambda: console.post(
                f"/workspaces/{workspace_id}/suspend",
                {"reason": "The invoice of 3 March is sixty days overdue"},
            ),
            AdminAction.WORKSPACE_SUSPENDED,
        ),
        ("POST", f"{ADMIN}/workspaces/{{workspace_id}}/unsuspend"): (
            lambda: console.post(f"/workspaces/{workspace_id}/unsuspend", {}),
            AdminAction.WORKSPACE_UNSUSPENDED,
        ),
        ("POST", f"{ADMIN}/workspaces/{{workspace_id}}/cancel"): (
            lambda: console.post(
                f"/workspaces/{workspace_id}/cancel",
                {"confirm_slug": slug},
            ),
            AdminAction.WORKSPACE_CANCELLED,
        ),
        ("PATCH", f"{ADMIN}/workspaces/{{workspace_id}}/erase-after"): (
            lambda: console.patch(
                f"/workspaces/{workspace_id}/erase-after",
                {"erase_after": (datetime.now(UTC) + timedelta(days=3)).isoformat()},
            ),
            AdminAction.WORKSPACE_ERASE_AFTER_CHANGED,
        ),
        ("POST", f"{ADMIN}/workspaces/{{workspace_id}}/restore"): (
            lambda: console.post(f"/workspaces/{workspace_id}/restore", {}),
            AdminAction.WORKSPACE_RESTORED,
        ),
        ("POST", f"{ADMIN}/users/{{user_id}}/deactivate"): (
            lambda: console.post(f"/users/{colleague}/deactivate", {}),
            AdminAction.USER_DEACTIVATED,
        ),
        ("POST", f"{ADMIN}/users/{{user_id}}/activate"): (
            lambda: console.post(f"/users/{colleague}/activate", {}),
            AdminAction.USER_ACTIVATED,
        ),
        ("POST", f"{ADMIN}/users/{{user_id}}/sessions/revoke"): (
            lambda: console.post(f"/users/{colleague}/sessions/revoke", {}),
            AdminAction.USER_SESSIONS_REVOKED,
        ),
        ("POST", f"{ADMIN}/users/{{user_id}}/verify-email"): (
            lambda: console.post(f"/users/{colleague}/verify-email", {}),
            AdminAction.USER_EMAIL_VERIFIED,
        ),
        # Billing. The ledger is not about any one workspace; a granted
        # plan is about exactly one.
        ("GET", f"{ADMIN}/billing/subscriptions"): (
            lambda: console.get("/billing/subscriptions"),
            AdminAction.SUBSCRIPTIONS_SEARCHED,
        ),
        ("GET", f"{ADMIN}/billing/events"): (
            lambda: console.get("/billing/events"),
            AdminAction.BILLING_EVENTS_READ,
        ),
        ("POST", f"{ADMIN}/billing/events/{{event_id}}/replay"): (
            lambda: console.post(f"/billing/events/{billing_event_id}/replay", {}),
            AdminAction.BILLING_EVENT_REPLAYED,
        ),
        ("POST", f"{ADMIN}/workspaces/{{workspace_id}}/plan-override"): (
            lambda: console.post(
                f"/workspaces/{workspace_id}/plan-override",
                {"plan": "growth", "reason": "Pilot until the contract lands"},
            ),
            AdminAction.PLAN_OVERRIDE_GRANTED,
        ),
        ("DELETE", f"{ADMIN}/workspaces/{{workspace_id}}/plan-override"): (
            lambda: console.delete(f"/workspaces/{workspace_id}/plan-override"),
            AdminAction.PLAN_OVERRIDE_REMOVED,
        ),
        # Operations. The queue read, then one job acted on, then the
        # pages that answer "is anything wrong".
        ("GET", f"{ADMIN}/jobs"): (
            lambda: console.get("/jobs"),
            AdminAction.JOBS_SEARCHED,
        ),
        ("GET", f"{ADMIN}/jobs/{{job_id}}"): (
            lambda: console.get(f"/jobs/{job_id}"),
            AdminAction.JOB_READ,
        ),
        ("POST", f"{ADMIN}/jobs/{{job_id}}/cancel"): (
            lambda: console.post(f"/jobs/{job_id}/cancel", {}),
            AdminAction.JOB_CANCELLED,
        ),
        ("POST", f"{ADMIN}/jobs/{{job_id}}/retry"): (
            lambda: console.post(f"/jobs/{job_id}/retry", {}),
            AdminAction.JOB_RETRIED,
        ),
        ("GET", f"{ADMIN}/webhooks/failures"): (
            lambda: console.get("/webhooks/failures"),
            AdminAction.WEBHOOK_FAILURES_READ,
        ),
        ("GET", f"{ADMIN}/integrations/whatsapp"): (
            lambda: console.get("/integrations/whatsapp"),
            AdminAction.WHATSAPP_HEALTH_READ,
        ),
        ("GET", f"{ADMIN}/health"): (
            lambda: console.get("/health"),
            AdminAction.HEALTH_READ,
        ),
        # Analytics. Aggregates, recorded like everything else.
        ("GET", f"{ADMIN}/analytics/overview"): (
            lambda: console.get("/analytics/overview"),
            AdminAction.ANALYTICS_READ,
        ),
        ("GET", f"{ADMIN}/analytics/growth"): (
            lambda: console.get("/analytics/growth"),
            AdminAction.ANALYTICS_READ,
        ),
        ("GET", f"{ADMIN}/analytics/revenue"): (
            lambda: console.get("/analytics/revenue"),
            AdminAction.ANALYTICS_READ,
        ),
        ("GET", f"{ADMIN}/analytics/ai"): (
            lambda: console.get("/analytics/ai"),
            AdminAction.ANALYTICS_READ,
        ),
        ("POST", f"{ADMIN}/workspaces/{{workspace_id}}/erase-now"): (
            lambda: console.post(
                f"/workspaces/{workspace_id}/erase-now",
                {"confirm_slug": slug},
            ),
            AdminAction.WORKSPACE_ERASED,
        ),
    }


# --- every route is audited -------------------------------------------------


def test_every_published_route_has_a_case(
    owner: Console,
    acme: Tenant,
    client: TestClient,
    db_session: Session,
) -> None:
    # The half of the arrangement that cannot be forgotten. A route added
    # to the router without a case here fails this rather than quietly
    # going unaudited in the test below.
    colleague = a_colleague(client, db_session, "colleague@example.com")

    assert (
        sorted(
            _calls(
                owner,
                colleague,
                acme.workspace_id,
                _a_conversation(acme),
                "acme-fashion",
                _a_billing_delivery(db_session),
                _a_job(db_session),
            )
        )
        == operations()
    )


def test_every_route_writes_exactly_one_entry(
    owner: Console,
    acme: Tenant,
    client: TestClient,
    db_session: Session,
) -> None:
    """Principle 2, over the whole surface, reads included.

    On this surface looking at somebody else's data is the sensitive act,
    so a log recording only writes would answer the wrong question. Each
    call is checked for one entry rather than at least one, because two
    rows for one act is a log that cannot be counted.
    """
    colleague = a_colleague(client, db_session, "colleague@example.com")

    for (method, path), (call, expected) in _calls(
        owner,
        colleague,
        acme.workspace_id,
        _a_conversation(acme),
        "acme-fashion",
        _a_billing_delivery(db_session),
        _a_job(db_session),
    ).items():
        before = len(entries(db_session))

        response = call()

        assert response.status_code < 400, f"{method} {path}: {response.text}"

        written = entries(db_session)

        assert len(written) == before + 1, f"{method} {path}"
        assert written[-1].action == expected, f"{method} {path}"


def test_an_entry_says_who_and_from_where(owner: Console, db_session: Session) -> None:
    owner.get("/me")

    (entry,) = entries(db_session, AdminAction.CONSOLE_OPENED)

    assert entry.actor_user_id == owner.user_id
    assert entry.actor_email == owner.email
    # Best effort and decides nothing. It is here because the question
    # asked after an incident is whether an entry looks like the
    # colleague it names.
    assert entry.ip_address is not None
    assert entry.user_agent is not None


# --- the log outlives its subject -------------------------------------------


def test_the_log_survives_the_workspace_it_names(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    """The point of the phase, as one test.

    A tenant's own audit log is erased with the workspace, which is
    right: the customer asked to be forgotten. This row is the record of
    what *staff* did, it belongs to the business that runs the platform,
    and it has to be readable afterwards -- still naming which account it
    was about.
    """
    business = sign_up(client, "business-owner@example.com")
    created = client.post(
        "/api/v1/workspaces",
        json={"name": "Acme Fashion", "slug": "acme-fashion"},
        headers=business,
    ).json()
    workspace_id = uuid.UUID(created["id"])

    # Written directly, because no route in this phase names a workspace
    # -- the console that reads one is Phase A2. What is under test is
    # the shape of the table, which is settled now and cannot be changed
    # cheaply once entries depend on it.
    audit = AdminAuditService(
        session=db_session,
        logs=AdminAuditLogRepository(db_session),
    )
    audit.did(
        AdminActor(user_id=owner.user_id, email=owner.email),
        AdminAction.CONSOLE_OPENED,
        workspace_id=workspace_id,
        workspace_slug=created["slug"],
    )
    db_session.commit()

    workspace = db_session.get(Workspace, workspace_id)
    assert workspace is not None
    WorkspaceRepository(db_session).erase(workspace)

    # Re-read, because the nulling happened in the database rather than
    # in the mapper: nothing in the ORM knows this row referred to the
    # workspace that was just deleted.
    db_session.expire_all()
    (entry,) = entries(db_session, AdminAction.CONSOLE_OPENED)

    assert entry.workspace_id is None
    # And this is why the slug is copied beside the id. Without it the
    # surviving row would say that somebody looked at something.
    assert entry.workspace_slug == "acme-fashion"


def test_the_log_survives_the_staff_member_who_wrote_it(
    owner: Console,
    client: TestClient,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    # The move an audit log exists to defeat: closing your own account to
    # remove yourself from the record of what you did.
    owner.get("/me")

    user = db_session.get(User, owner.user_id)
    assert user is not None
    user_repository.delete(user)
    db_session.flush()

    db_session.expire_all()
    (entry,) = entries(db_session, AdminAction.CONSOLE_OPENED)

    assert entry.actor_user_id is None
    assert entry.actor_email == "platform-owner@example.com"


# --- reading it -------------------------------------------------------------


def test_the_page_is_newest_first_and_counts_everything(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.get("/me")
    owner.post("/staff", {"user_id": colleague, "role": StaffRole.SUPPORT.value})

    body = owner.get("/audit").json()

    assert body["items"][0]["action"] == AdminAction.STAFF_GRANTED.value
    assert body["items"][1]["action"] == AdminAction.CONSOLE_OPENED.value
    assert body["total"] == 2


def test_reading_the_log_is_recorded_but_not_shown_to_its_reader(
    owner: Console,
) -> None:
    # Written after the page is queried, so nobody is handed their own
    # arrival at the top of what they asked for. It is there next time.
    first = owner.get("/audit").json()

    assert first["items"] == []

    second = owner.get("/audit").json()

    assert [item["action"] for item in second["items"]] == [
        AdminAction.AUDIT_READ.value
    ]


def test_the_page_can_be_narrowed(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.get("/me")
    owner.post("/staff", {"user_id": colleague, "role": StaffRole.SUPPORT.value})

    narrowed = owner.get("/audit", action=AdminAction.STAFF_GRANTED.value).json()

    assert narrowed["total"] == 1
    assert narrowed["items"][0]["target_user_id"] == colleague

    # The count filters the same way the page does. A total that did not
    # would be a pager that runs out early, and nobody notices until
    # somebody is looking for one particular afternoon.
    assert len(narrowed["items"]) == narrowed["total"]


def test_a_page_can_be_narrowed_to_one_colleague_and_one_afternoon(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    owner.get("/me")

    tomorrow = datetime.now(UTC) + timedelta(days=1)

    assert owner.get("/audit", actor_user_id=owner.user_id).json()["total"] == 1
    assert owner.get("/audit", actor_user_id=9999).json()["total"] == 0
    # `until` is exclusive, like every other period here, so consecutive
    # ranges neither overlap nor leave a gap.
    assert owner.get("/audit", until=tomorrow.isoformat()).json()["total"] >= 1
    assert owner.get("/audit", since=tomorrow.isoformat()).json()["total"] == 0


def test_the_page_is_a_page(owner: Console) -> None:
    owner.get("/me")
    owner.get("/me")
    owner.get("/me")

    body = owner.get("/audit", page=1, page_size=2).json()

    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["page_size"] == 2


def test_support_may_not_read_the_platform_log(
    client: TestClient,
    db_session: Session,
) -> None:
    # Reading what every colleague has done is administration by
    # definition, which is the same line the tenant audit log draws.
    console = Console(client, db_session, "support@example.com", StaffRole.SUPPORT)

    response = console.get("/audit")

    assert response.status_code == 403
    assert response.json()["code"] == "insufficient_staff_role"


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE", "PUT"])
def test_there_is_no_way_to_edit_or_remove_an_entry(
    owner: Console,
    method: str,
) -> None:
    """Append-only, at any rank, as a route that does not exist.

    Not a rule somebody has to remember: there is no handler, and no
    method on the repository behind it if one were ever added.
    """
    response = owner.client.request(
        method,
        f"{ADMIN}/audit",
        headers=owner.headers,
        json={},
    )

    assert response.status_code == 405


def test_nothing_in_the_application_updates_or_deletes_an_entry(
    db_session: Session,
) -> None:
    # The repository is the only way in, and it can append and read.
    # Written as a test because "there is no method" is a property that a
    # helpful refactor could take away.
    surface = dir(AdminAuditLogRepository)

    assert "record" in surface
    assert not [name for name in surface if "delete" in name or "update" in name]


def test_the_table_orders_by_its_sequence_rather_than_a_timestamp(
    owner: Console,
    db_session: Session,
) -> None:
    # Two entries written in one transaction share a created_at to the
    # microsecond, so the sequence is the only ordering that holds.
    owner.get("/me")
    owner.get("/me")

    written = db_session.scalars(
        select(AdminAuditLog).order_by(AdminAuditLog.sequence)
    ).all()

    assert [entry.sequence for entry in written] == sorted(
        entry.sequence for entry in written
    )
    assert len({entry.sequence for entry in written}) == len(written)
