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
from app.models.staff_member import StaffRole
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.admin_audit_log_repository import AdminAuditLogRepository
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


def _calls(
    console: Console,
    colleague: int,
    workspace_id: str,
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

    assert sorted(_calls(owner, colleague, acme.workspace_id)) == operations()


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
