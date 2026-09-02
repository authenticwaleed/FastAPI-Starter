"""Phase A3 acceptance: reading a customer's data, for a reason, until a date.

The most dangerous phase in the plan, and most of this file is about the
four properties that make it safe rather than about the routes.

It ends by itself, and nothing has to run for that to happen. The
customer sees it in their own audit log, with the reason given. It reads
and cannot write. And it never appears in the customer's member list or
in what they are billed for -- a support engineer is not a colleague.

The last of those is the one that would be easiest to break by accident,
which is why it is tested from three directions.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import StaffCannotActAsTenantError
from app.models.admin_audit_log import AdminAction
from app.models.audit_log import AuditEvent, AuditLog
from app.models.staff_member import StaffMember, StaffRole
from app.models.support_grant import SupportGrant
from app.models.usage_record import UsageMetric
from app.models.workspace import Workspace
from app.models.workspace_membership import WorkspaceMembership, WorkspaceRole
from app.repositories.usage_repository import UsageRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.plans import PlanTier
from app.services.workspace_service import WorkspaceAccess
from tests.support.staff import ADMIN, Console, entries, operations
from tests.support.tenants import Tenant

REASON = "Investigating the delivery failure reported on Tuesday"


@pytest.fixture
def console(client: TestClient, db_session: Session) -> Console:
    """A support engineer: the rank that asks for access."""
    return Console(client, db_session, "support@example.com", StaffRole.SUPPORT)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _ask(console: Console, tenant: Tenant, **body: Any) -> Any:
    return console.post(
        f"/workspaces/{tenant.workspace_id}/support-access",
        {"reason": REASON} | body,
    )


def _granted(console: Console, tenant: Tenant, **body: Any) -> Any:
    response = _ask(console, tenant, **body)
    assert response.status_code == 201, response.text

    return response.json()


def _conversations(console: Console, tenant: Tenant) -> Any:
    return console.get(f"/workspaces/{tenant.workspace_id}/conversations")


def _a_conversation(tenant: Tenant) -> str:
    """One real thread in the customer's inbox, for support to read.

    Through the customer's own API rather than written straight to the
    table, because what this file is testing is that staff see what the
    customer sees.
    """
    response = tenant.client.post(
        tenant.path("conversations"),
        json={"contact_id": tenant.contact()},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text

    return str(response.json()["id"])


def _grant_row(session: Session) -> SupportGrant:
    grant = session.scalar(select(SupportGrant))
    assert grant is not None

    return grant


def _tenant_log(session: Session, event: AuditEvent) -> list[AuditLog]:
    return list(
        session.scalars(
            select(AuditLog).where(AuditLog.event == event).order_by(AuditLog.sequence)
        ).all()
    )


# --- the door ---------------------------------------------------------------


def test_reading_without_a_grant_is_refused(
    console: Console,
    acme: Tenant,
) -> None:
    response = _conversations(console, acme)

    assert response.status_code == 403
    assert response.json()["code"] == "support_access_required"


def test_reading_with_a_live_grant_is_allowed(
    console: Console,
    acme: Tenant,
) -> None:
    _granted(console, acme)

    response = _conversations(console, acme)

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_an_expired_grant_opens_nothing(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The property the whole phase rests on, and nothing runs to enforce it.

    An expired grant simply stops matching the lookup that opens the
    door, so expiry is a fact about the data rather than about a job
    somebody has to remember to schedule.
    """
    _granted(console, acme)
    assert _conversations(console, acme).status_code == 200

    grant = _grant_row(db_session)
    grant.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    refused = _conversations(console, acme)

    assert refused.status_code == 403
    assert refused.json()["code"] == "support_access_required"


def test_a_grant_ended_early_opens_nothing(
    console: Console,
    acme: Tenant,
) -> None:
    _granted(console, acme)

    assert (
        console.delete(f"/workspaces/{acme.workspace_id}/support-access").status_code
        == 204
    )
    assert _conversations(console, acme).status_code == 403


def test_a_grant_opens_one_workspace_and_not_another(
    console: Console,
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    # The grant names a workspace. Holding one is not a key to the
    # platform, which is the difference between this and the standing
    # access it replaces.
    beta = Tenant(client, user_repository, membership_repository, "beta-goods")
    _granted(console, acme)

    assert _conversations(console, acme).status_code == 200
    assert _conversations(console, beta).status_code == 403


def test_one_staff_members_grant_is_not_anothers(
    console: Console,
    acme: Tenant,
    client: TestClient,
    db_session: Session,
) -> None:
    _granted(console, acme)
    colleague = Console(client, db_session, "other@example.com", StaffRole.ADMIN)

    assert _conversations(colleague, acme).status_code == 403


# --- how long it lasts ------------------------------------------------------


def test_a_grant_defaults_to_the_configured_window(
    console: Console,
    acme: Tenant,
) -> None:
    granted = _granted(console, acme)
    expires = datetime.fromisoformat(granted["expires_at"])

    # Four hours, which is a shift. Compared loosely because the clock
    # moves between the request and the assertion.
    assert (
        timedelta(hours=3, minutes=59)
        < expires - datetime.now(UTC)
        < timedelta(hours=4, minutes=1)
    )


def test_a_longer_window_can_be_asked_for(console: Console, acme: Tenant) -> None:
    granted = _granted(console, acme, hours=12)
    expires = datetime.fromisoformat(granted["expires_at"])

    assert expires - datetime.now(UTC) > timedelta(hours=11)


def test_too_long_is_refused_rather_than_shortened(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """Refused, which is the plan's word and the right one.

    Somebody quietly given four hours when they asked for two days
    believes they have two days, and finds out otherwise in the middle of
    whatever they were investigating.
    """
    response = _ask(console, acme, hours=48)

    assert response.status_code == 422
    assert db_session.scalar(select(SupportGrant)) is None


def test_a_reason_is_required_and_has_to_say_something(
    console: Console,
    acme: Tenant,
) -> None:
    # It ends up in the customer's own audit log, where "check" is not an
    # answer to why somebody read their account.
    assert (
        console.post(
            f"/workspaces/{acme.workspace_id}/support-access",
            {"hours": 4},
        ).status_code
        == 422
    )
    assert (
        console.post(
            f"/workspaces/{acme.workspace_id}/support-access",
            {"reason": "check"},
        ).status_code
        == 422
    )


def test_a_second_grant_while_one_is_live_is_refused(
    console: Console,
    acme: Tenant,
) -> None:
    # A grant carries a reason and an expiry recorded together. Pushing
    # the expiry out later would leave the reason describing a window it
    # no longer covers.
    _granted(console, acme)

    again = _ask(console, acme)

    assert again.status_code == 409
    assert again.json()["code"] == "support_access_already_granted"


def test_a_grant_can_be_asked_for_again_once_the_first_has_ended(
    console: Console,
    acme: Tenant,
) -> None:
    _granted(console, acme)
    console.delete(f"/workspaces/{acme.workspace_id}/support-access")

    assert _ask(console, acme).status_code == 201


# --- what the customer sees -------------------------------------------------


def test_the_customer_sees_the_access_in_their_own_log(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """Principle four: no silent power.

    The entry is in the business's own audit log, with the address of
    whoever asked and the reason they gave -- which is what turns "a
    staff member read your account" from an alarm into an answer.
    """
    _granted(console, acme)

    (entry,) = _tenant_log(db_session, AuditEvent.SUPPORT_ACCESS_GRANTED)

    assert entry.workspace_id == uuid.UUID(acme.workspace_id)
    assert entry.meta["staff_email"] == "support@example.com"
    assert entry.meta["reason"] == REASON
    assert entry.meta["expires_at"]


def test_the_customers_entry_never_looks_like_one_of_their_own_people(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The single property this design exists to protect.

    A support engineer must never appear in a business's log as one of
    their colleagues. The event name is what says a staff member did it,
    and the actor is empty because no member of their team did.
    """
    _granted(console, acme)

    (entry,) = _tenant_log(db_session, AuditEvent.SUPPORT_ACCESS_GRANTED)

    assert entry.actor_user_id is None
    assert entry.actor_email is None
    assert entry.event == AuditEvent.SUPPORT_ACCESS_GRANTED


def test_the_customer_sees_it_end(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    _granted(console, acme)
    console.delete(f"/workspaces/{acme.workspace_id}/support-access")

    (ended,) = _tenant_log(db_session, AuditEvent.SUPPORT_ACCESS_ENDED)

    assert ended.meta["staff_email"] == "support@example.com"


def test_the_customer_can_read_those_entries_on_their_own_surface(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # Through their own API, which is the point of writing them there.
    # On a plan that includes an audit log -- which is a real gap for a
    # free-plan customer, and one this phase records rather than closes.
    acme.on_plan(db_session, PlanTier.BUSINESS)
    _granted(console, acme)

    page = acme.client.get(
        acme.path("audit-logs"),
        headers=acme.owner_headers,
        params={"event": AuditEvent.SUPPORT_ACCESS_GRANTED.value},
    )

    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["actor"] is None


# --- it is not a membership -------------------------------------------------


def test_a_grant_writes_no_membership(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    before = db_session.scalars(select(WorkspaceMembership)).all()

    _granted(console, acme)

    after = db_session.scalars(select(WorkspaceMembership)).all()

    assert len(after) == len(before)


def test_a_grant_does_not_appear_in_the_customers_member_list(
    console: Console,
    acme: Tenant,
) -> None:
    _granted(console, acme)

    listed = acme.client.get(acme.path("members"), headers=acme.owner_headers).json()

    assert [member["email"] for member in listed] == ["owner-acme-fashion@example.com"]


def test_a_grant_is_not_a_seat_the_customer_pays_for(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # Counted from memberships, so a grant that wrote one would quietly
    # bill a business for the support engineer looking at their account.
    usage = UsageRepository(db_session)
    before = usage.team_members(uuid.UUID(acme.workspace_id))

    _granted(console, acme)

    assert usage.team_members(uuid.UUID(acme.workspace_id)) == before
    assert UsageMetric.TEAM_MEMBERS.value == "team_members"


# --- it reads, and cannot write ---------------------------------------------


def test_no_admin_route_can_write_a_customers_data(console: Console) -> None:
    """The acceptance criterion, over the whole published surface.

    Every verb other than GET on `/admin` is checked by hand here,
    because "no route writes tenant data" is a claim about the router
    rather than about any one handler -- and a route added next month is
    covered without anybody remembering.
    """
    writes = [(method, path) for method, path in operations() if method != "GET"]

    # Staff membership of the platform, and asking for or ending access.
    # None of them touches a customer's own data.
    assert sorted(writes) == [
        ("DELETE", f"{ADMIN}/staff/{{user_id}}"),
        ("DELETE", f"{ADMIN}/workspaces/{{workspace_id}}/support-access"),
        ("PATCH", f"{ADMIN}/staff/{{user_id}}"),
        ("POST", f"{ADMIN}/staff"),
        ("POST", f"{ADMIN}/workspaces/{{workspace_id}}/support-access"),
    ]


def test_a_staff_actor_holds_the_viewers_role() -> None:
    # No database needed: the rule is a property of the object.
    access = WorkspaceAccess(
        workspace=Workspace(id=uuid.uuid4(), name="Acme", slug="acme"),
        staff_actor=StaffMember(user_id=1, role=StaffRole.OWNER),
    )

    assert access.role == WorkspaceRole.VIEWER


def test_a_staff_actor_cannot_be_the_actor_on_a_tenant_entry() -> None:
    """Raises rather than answering, which is the guard.

    Returning their id would put a support engineer in a business's audit
    log among their own colleagues; returning null would say a payment
    provider did it. Both are worse than a refusal nobody should ever
    see.
    """
    access = WorkspaceAccess(
        workspace=Workspace(id=uuid.uuid4(), name="Acme", slug="acme"),
        staff_actor=StaffMember(user_id=1, role=StaffRole.OWNER),
    )

    with pytest.raises(StaffCannotActAsTenantError):
        _ = access.actor_user_id


def test_access_needs_exactly_one_kind_of_proof() -> None:
    # Neither is a workspace nobody proved they could reach; both is a
    # staff member wearing a customer's role. Unconstructable rather than
    # discouraged.
    workspace = Workspace(id=uuid.uuid4(), name="Acme", slug="acme")

    with pytest.raises(ValueError):
        WorkspaceAccess(workspace=workspace)

    with pytest.raises(ValueError):
        WorkspaceAccess(
            workspace=workspace,
            membership=WorkspaceMembership(role=WorkspaceRole.OWNER),
            staff_actor=StaffMember(user_id=1, role=StaffRole.OWNER),
        )


def test_the_granted_inbox_offers_no_assigned_to_filter(console: Console) -> None:
    # "Assigned to me" means nothing to somebody who is not on the team,
    # and offering it would be the first place a staff actor started to
    # look like a colleague.
    spec = console.client.app.openapi()  # type: ignore[attr-defined]
    path = spec["paths"]["/api/v1/admin/workspaces/{workspace_id}/conversations"]["get"]

    assert "assigned_to" not in {
        parameter["name"] for parameter in path.get("parameters", [])
    }


# --- reading it back --------------------------------------------------------


def test_every_read_through_a_grant_is_recorded(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """Per request, not once per grant.

    The grant says somebody was allowed to look. These say what they
    actually opened, which is the question asked afterwards.
    """
    _granted(console, acme)
    _conversations(console, acme)
    _conversations(console, acme)

    assert len(entries(db_session, AdminAction.CONVERSATIONS_READ)) == 2


def test_reading_a_thread_records_which_thread(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # "They read the inbox" and "they read this customer's thread with
    # this person" are different answers to give afterwards.
    conversation_id = _a_conversation(acme)
    _granted(console, acme)

    response = console.get(
        f"/workspaces/{acme.workspace_id}/conversations/{conversation_id}/messages"
    )
    assert response.status_code == 200, response.text

    (entry,) = entries(db_session, AdminAction.MESSAGES_READ)

    assert entry.meta["conversation_id"] == conversation_id
    assert entry.workspace_slug == "acme-fashion"


def test_support_sees_the_same_inbox_the_customer_does(
    console: Console,
    acme: Tenant,
) -> None:
    # The same service and the same renderer. A second reading path would
    # eventually show one of them something the other cannot see, which
    # is the opposite of what a grant is for.
    conversation_id = _a_conversation(acme)
    _granted(console, acme)

    theirs = acme.client.get(
        acme.path("conversations"),
        headers=acme.owner_headers,
    ).json()
    ours = _conversations(console, acme).json()

    assert [item["id"] for item in ours["items"]] == [conversation_id]
    assert ours["items"] == theirs["items"]


def test_the_platform_records_the_grant_with_its_reason(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    _granted(console, acme, hours=6)

    (entry,) = entries(db_session, AdminAction.SUPPORT_ACCESS_GRANTED)

    assert entry.meta["reason"] == REASON
    assert entry.meta["hours"] == 6
    assert entry.workspace_slug == "acme-fashion"


def test_ending_access_twice_records_one_entry(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # Ending access you no longer hold is not an error, and answers the
    # same way -- but it is not a second thing that happened.
    _granted(console, acme)
    console.delete(f"/workspaces/{acme.workspace_id}/support-access")
    console.delete(f"/workspaces/{acme.workspace_id}/support-access")

    assert len(entries(db_session, AdminAction.SUPPORT_ACCESS_REVOKED)) == 1
    assert len(_tenant_log(db_session, AuditEvent.SUPPORT_ACCESS_ENDED)) == 1


def test_the_history_of_a_workspaces_grants_is_readable_by_an_admin(
    console: Console,
    acme: Tenant,
    client: TestClient,
    db_session: Session,
) -> None:
    """The review surface for the power the other two routes hand out.

    History as well as what is live, because a list of only the live ones
    is almost always empty and the question is about the past.
    """
    _granted(console, acme)
    console.delete(f"/workspaces/{acme.workspace_id}/support-access")

    overseer = Console(client, db_session, "overseer@example.com", StaffRole.ADMIN)
    listed = overseer.get(f"/workspaces/{acme.workspace_id}/support-access").json()

    assert len(listed) == 1
    assert listed[0]["staff_email"] == "support@example.com"
    assert listed[0]["reason"] == REASON
    assert listed[0]["live"] is False
    assert listed[0]["revoked_at"] is not None


def test_support_may_not_review_who_has_had_access(
    console: Console,
    acme: Tenant,
) -> None:
    # Asking is `support`; reviewing is `admin`. The rank that answers
    # tickets is not the rank that oversees whether it should have.
    response = console.get(f"/workspaces/{acme.workspace_id}/support-access")

    assert response.status_code == 403
    assert response.json()["code"] == "insufficient_staff_role"


def test_an_unknown_workspace_is_a_404_not_a_grant(console: Console) -> None:
    response = console.post(
        f"/workspaces/{uuid.uuid4()}/support-access",
        {"reason": REASON},
    )

    assert response.status_code == 404
