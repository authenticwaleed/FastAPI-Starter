"""Phase A1 acceptance: the platform door, and who holds a key.

The first three tests are the phase. Everything under `/admin` refuses
somebody who is not staff, refuses somebody whose access was taken away,
and refuses a session that has been left sitting -- and the first of
those is written by introspection over the router, so a route added next
month is covered without anybody remembering to add it here.

The rest is the ladder and the last-owner rule, which are ordinary
administration and would still be worth testing on a surface with far
less at stake.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAction
from app.models.staff_member import StaffMember, StaffRole
from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.user_repository import UserRepository
from tests.support.staff import (
    ADMIN,
    Console,
    a_colleague,
    entries,
    operations,
)
from tests.support.tenants import sign_up

OWNER = StaffRole.OWNER
ADMIN_ROLE = StaffRole.ADMIN
SUPPORT = StaffRole.SUPPORT


def _addressable(path: str) -> str:
    """A path with its parameters filled in with something.

    Anything will do. Every test using this expects to be refused before
    the value is ever looked at -- path validation happens after the
    dependencies, which is itself worth knowing.
    """
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.fixture
def owner(client: TestClient, db_session: Session) -> Console:
    return Console(client, db_session, "platform-owner@example.com", OWNER)


# --- the door ---------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), operations())
def test_a_signed_in_stranger_is_refused_by_every_admin_route(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    # The acceptance criterion of the phase, over the whole router. A 403
    # rather than a 404: this caller is authenticated, and pretending the
    # console is not there would only puzzle a colleague whose access was
    # withdrawn this morning.
    headers = sign_up(client, "not-staff@example.com")

    response = client.request(method, _addressable(path), headers=headers, json={})

    assert response.status_code == 403, path
    assert response.json()["code"] == "not_staff"


@pytest.mark.parametrize(("method", "path"), operations())
def test_an_unauthenticated_caller_is_refused_by_every_admin_route(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.request(method, _addressable(path), json={})

    assert response.status_code == 401, path


def test_a_revoked_staff_member_is_refused_on_the_next_request(
    owner: Console,
    db_session: Session,
) -> None:
    assert owner.get("/me").status_code == 200

    owner.revoked()

    refused = owner.get("/me")

    assert refused.status_code == 403
    assert refused.json()["code"] == "not_staff"


def test_a_session_left_idle_is_refused_by_the_console_alone(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    """The whole of "staff do not reuse ordinary sessions".

    One account, one password, one sign-in -- and a window on this
    surface short enough that a console able to read any customer's
    account is not still open on an unattended laptop. The same session
    keeps working on the tenant surface, which is what makes this a
    policy about the console rather than about the person.
    """
    session = db_session.scalar(
        select(UserSession).where(UserSession.user_id == owner.user_id)
    )
    assert session is not None
    session.last_used_at = datetime.now(UTC) - timedelta(hours=8)
    db_session.flush()

    refused = owner.get("/me")

    assert refused.status_code == 401
    assert refused.json()["code"] == "admin_session_expired"

    still_working = client.get("/api/v1/auth/me", headers=owner.headers)

    assert still_working.status_code == 200


def test_staff_access_grants_nothing_inside_a_customer_workspace(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    """Principle 1, as a test: the tenant surface does not change.

    Reading a customer's workspace is Phase A3, behind a time-boxed grant
    the customer can see. Until then a staff member is exactly as much a
    stranger to a business as anybody else.
    """
    stranger = sign_up(client, "business-owner@example.com")
    workspace_id = client.post(
        "/api/v1/workspaces",
        json={"name": "Acme", "slug": "acme"},
        headers=stranger,
    ).json()["id"]

    response = client.get(
        f"/api/v1/workspaces/{workspace_id}",
        headers=owner.headers,
    )

    assert response.status_code == 404


# --- what each rank reaches -------------------------------------------------


@pytest.mark.parametrize(
    ("role", "me", "list_staff", "grant"),
    [
        (SUPPORT, 200, 403, 403),
        (ADMIN_ROLE, 200, 200, 403),
        (OWNER, 200, 200, 201),
    ],
)
def test_each_rank_reaches_exactly_what_it_should(
    client: TestClient,
    db_session: Session,
    role: StaffRole,
    me: int,
    list_staff: int,
    grant: int,
) -> None:
    console = Console(client, db_session, f"staff-{role.value}@example.com", role)
    colleague = a_colleague(client, db_session, f"new-{role.value}@example.com")

    assert console.get("/me").status_code == me
    assert console.get("/staff").status_code == list_staff
    assert (
        console.post(
            "/staff",
            {"user_id": colleague, "role": SUPPORT.value},
        ).status_code
        == grant
    )


def test_the_console_says_who_you_are_and_what_you_may_do(owner: Console) -> None:
    body = owner.get("/me").json()

    assert body["user_id"] == owner.user_id
    assert body["email"] == owner.email
    assert body["role"] == OWNER.value
    assert body["revoked_at"] is None
    # Null for the first owner and only for them: nobody existed who
    # could have granted it.
    assert body["granted_by_user_id"] is None


# --- granting, changing, revoking -------------------------------------------


def test_granting_promotes_an_existing_account_and_records_who_did_it(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    colleague = a_colleague(client, db_session, "colleague@example.com")

    response = owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})

    assert response.status_code == 201
    assert response.json()["role"] == SUPPORT.value
    assert response.json()["granted_by_user_id"] == owner.user_id

    (recorded,) = entries(db_session, AdminAction.STAFF_GRANTED)

    # Both ends of the act, which is what makes the row worth keeping:
    # who did it and who it was done to.
    assert recorded.actor_user_id == owner.user_id
    assert recorded.actor_email == owner.email
    assert recorded.target_user_id == colleague
    assert recorded.meta["role"] == SUPPORT.value


def test_granting_to_an_unknown_account_is_a_404(owner: Console) -> None:
    assert (
        owner.post("/staff", {"user_id": 9999, "role": SUPPORT.value}).status_code
        == 404
    )


def test_granting_twice_is_refused_rather_than_treated_as_a_change(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    # Changing a rank is a PATCH, and it is the request that gets
    # recorded as a change. Accepting a second POST would lose that.
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})

    again = owner.post("/staff", {"user_id": colleague, "role": ADMIN_ROLE.value})

    assert again.status_code == 409
    assert again.json()["code"] == "already_staff"


def test_re_granting_reinstates_the_row_that_records_their_history(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    colleague = a_colleague(client, db_session, "returning@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})
    owner.delete(f"/staff/{colleague}")

    before = db_session.scalar(
        select(StaffMember).where(StaffMember.user_id == colleague)
    )
    assert before is not None
    was = before.id

    response = owner.post("/staff", {"user_id": colleague, "role": ADMIN_ROLE.value})

    assert response.status_code == 201
    assert response.json()["revoked_at"] is None

    after = db_session.scalar(
        select(StaffMember).where(StaffMember.user_id == colleague)
    )
    assert after is not None
    # One row, one history. A second row would mean reading two to find
    # out what somebody has had and when.
    assert after.id == was
    assert entries(db_session, AdminAction.STAFF_GRANTED)[-1].meta["reinstated"] is True


def test_changing_a_rank_records_both_of_them(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})

    response = owner.patch(f"/staff/{colleague}", {"role": ADMIN_ROLE.value})

    assert response.status_code == 200
    assert response.json()["role"] == ADMIN_ROLE.value

    (recorded,) = entries(db_session, AdminAction.STAFF_ROLE_CHANGED)

    # "Promoted to admin" without the rank they held is half an answer,
    # and this is the entry an investigation comes looking for.
    assert recorded.meta["from"] == SUPPORT.value
    assert recorded.meta["to"] == ADMIN_ROLE.value


def test_a_rank_change_to_the_rank_they_hold_records_nothing(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})

    assert (
        owner.patch(f"/staff/{colleague}", {"role": SUPPORT.value}).status_code == 200
    )

    # A log full of entries saying somebody saved a form without changing
    # it is one nobody reads.
    assert entries(db_session, AdminAction.STAFF_ROLE_CHANGED) == []


def test_revoking_keeps_the_row_and_stamps_it(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})

    response = owner.delete(f"/staff/{colleague}")

    assert response.status_code == 200
    assert response.json()["revoked_at"] is not None

    (recorded,) = entries(db_session, AdminAction.STAFF_REVOKED)

    assert recorded.target_user_id == colleague
    assert recorded.meta["role"] == SUPPORT.value


def test_revoking_twice_is_the_same_answer_and_the_same_timestamp(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    # Two people turning off the same access should get the same answer
    # whichever of them was first, and the timestamp should stay the one
    # from when it actually stopped working.
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})

    first = owner.delete(f"/staff/{colleague}")
    second = owner.delete(f"/staff/{colleague}")

    assert second.status_code == 200
    # The same instant, parsed rather than compared as text: one response
    # is serialised from the value Python set and the other from what the
    # database rendered it back as, in the server's own timezone.
    assert datetime.fromisoformat(
        second.json()["revoked_at"]
    ) == datetime.fromisoformat(first.json()["revoked_at"])
    assert len(entries(db_session, AdminAction.STAFF_REVOKED)) == 1


def test_a_revoked_colleague_cannot_have_their_rank_adjusted(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    # A revoked row is history rather than a colleague. Granting is the
    # way back in, and it is the act that gets recorded.
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})
    owner.delete(f"/staff/{colleague}")

    response = owner.patch(f"/staff/{colleague}", {"role": ADMIN_ROLE.value})

    assert response.status_code == 404
    assert response.json()["code"] == "staff_member_not_found"


# --- the last owner ---------------------------------------------------------


def test_the_last_owner_cannot_revoke_themselves(owner: Console) -> None:
    response = owner.delete(f"/staff/{owner.user_id}")

    assert response.status_code == 409
    assert response.json()["code"] == "last_staff_owner"


def test_the_last_owner_cannot_demote_themselves(owner: Console) -> None:
    # Only an owner may grant access, so a platform with no live owner is
    # a console nobody can ever be added to again without a database
    # client and a deployment.
    response = owner.patch(f"/staff/{owner.user_id}", {"role": ADMIN_ROLE.value})

    assert response.status_code == 409


def test_an_owner_may_step_down_once_there_is_another(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    colleague = a_colleague(client, db_session, "second-owner@example.com")
    owner.post("/staff", {"user_id": colleague, "role": OWNER.value})

    response = owner.patch(f"/staff/{owner.user_id}", {"role": ADMIN_ROLE.value})

    assert response.status_code == 200
    assert response.json()["role"] == ADMIN_ROLE.value


# --- the list ---------------------------------------------------------------


def test_the_staff_list_keeps_revoked_rows(
    owner: Console,
    client: TestClient,
    db_session: Session,
) -> None:
    # The useful half of the screen after an incident: who used to have
    # this, and when it was taken away.
    colleague = a_colleague(client, db_session, "colleague@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})
    owner.delete(f"/staff/{colleague}")

    listed = {row["user_id"]: row for row in owner.get("/staff").json()}

    assert listed[owner.user_id]["revoked_at"] is None
    assert listed[colleague]["revoked_at"] is not None


def test_the_platform_is_not_a_way_to_create_accounts(owner: Console) -> None:
    # No endpoint here makes a user, on purpose: staff are ordinary
    # accounts that have been promoted, which is what keeps one password
    # and one way back in for everybody.
    #
    # Written against the verb rather than the path, because a later
    # phase does add a read-only `/admin/users` for support to search --
    # and refusing that would be this test outliving its own point.
    assert not [
        (method, path)
        for method, path in operations()
        if method == "POST" and path.endswith("/users")
    ]


def test_deleting_a_staff_account_takes_the_staff_row_with_it(
    owner: Console,
    client: TestClient,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    """The row says something about an account and means nothing without it.

    What must outlive the account is the record of what they did, and
    that is `admin_audit_logs` -- which keeps the address rather than the
    id for exactly this reason. See the audit tests beside this file.
    """
    colleague = a_colleague(client, db_session, "leaving@example.com")
    owner.post("/staff", {"user_id": colleague, "role": SUPPORT.value})

    user = db_session.get(User, colleague)
    assert user is not None
    user_repository.delete(user)
    db_session.flush()

    assert (
        db_session.scalar(select(StaffMember).where(StaffMember.user_id == colleague))
        is None
    )


def test_a_path_parameter_is_never_looked_at_before_the_guard(
    client: TestClient,
) -> None:
    # Not a curiosity: it is what makes the introspective tests above
    # honest, because they fill every parameter with the same "1".
    headers = sign_up(client, "not-staff@example.com")

    response = client.delete(
        f"{ADMIN}/staff/{uuid.uuid4()}",
        headers=headers,
    )

    assert response.status_code == 403
