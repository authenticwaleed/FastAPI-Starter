"""Phase 8 acceptance: the shared inbox a dashboard is built on.

What the phase asks for is one screen's worth of API -- a row that can be
rendered without asking five more questions, filters an agent actually
reaches for, and a defined answer to "how many of these has nobody read".
So the tests here are mostly about the shape of one response and the
number of queries behind it, rather than about the lifecycle, which Phase
6 already covers.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.workspace_membership import WorkspaceRole
from app.repositories.conversation_repository import PREVIEW_LENGTH
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from tests.support.whatsapp import PHONE_NUMBER_ID, inbound_payload, sign

PASSWORD = "correct horse battery staple"
WEBHOOK = "/api/v1/webhooks/whatsapp"

AYESHA = "+923001234567"
BILAL = "+923009876543"


def _sign_up(client: TestClient, email: str, name: str = "Someone") -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


def _app_secret() -> str:
    secret = get_settings().whatsapp_app_secret
    assert secret is not None

    return secret.get_secret_value()


class Business:
    """One workspace with a WhatsApp number connected, and its team."""

    def __init__(
        self,
        client: TestClient,
        users: UserRepository,
        memberships: WorkspaceMembershipRepository,
        slug: str,
        phone_number_id: str = PHONE_NUMBER_ID,
    ) -> None:
        self._client = client
        self._users = users
        self._memberships = memberships
        self._phone_number_id = phone_number_id

        self.owner_headers = _sign_up(client, f"owner-{slug}@example.com", "Owner")
        self.owner_id = self.user_id(f"owner-{slug}@example.com")
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": slug.title(), "slug": slug},
            headers=self.owner_headers,
        ).json()["id"]

        client.post(
            f"/api/v1/workspaces/{self.workspace_id}/integrations/whatsapp/connect",
            json={
                "phone_number": "+15550001111",
                "external_phone_number_id": phone_number_id,
                "access_token": "a-provider-token",
            },
            headers=self.owner_headers,
        )

    def user_id(self, email: str) -> int:
        user = self._users.get_by_email(email)
        assert user is not None

        return user.id

    def member(
        self,
        email: str,
        role: WorkspaceRole = WorkspaceRole.AGENT,
        name: str = "Colleague",
    ) -> tuple[dict[str, str], int]:
        headers = _sign_up(self._client, email, name)
        user_id = self.user_id(email)
        self._memberships.create(
            workspace_id=uuid.UUID(self.workspace_id),
            user_id=user_id,
            role=role,
        )

        return headers, user_id

    def path(self, conversation_id: str | None = None, suffix: str = "") -> str:
        base = f"/api/v1/workspaces/{self.workspace_id}/conversations"

        if conversation_id is None:
            return base

        return f"{base}/{conversation_id}{suffix}"

    def contact(self, number: str = AYESHA, name: str | None = None) -> str:
        body: dict[str, Any] = {"phone_number": number}

        if name is not None:
            body["name"] = name

        return self._client.post(
            f"/api/v1/workspaces/{self.workspace_id}/contacts",
            json=body,
            headers=self.owner_headers,
        ).json()["id"]

    def open(self, contact_id: str | None = None) -> dict[str, Any]:
        response = self._client.post(
            self.path(),
            json={"contact_id": contact_id or self.contact()},
            headers=self.owner_headers,
        )
        assert response.status_code == 201, response.text

        return response.json()

    def receives(
        self,
        text: str = "Do you have this in medium?",
        *,
        from_number: str = "923001234567",
        message_id: str = "wamid.INBOUND1",
        profile_name: str | None = "Ayesha",
    ) -> None:
        """A customer writes in, through the real webhook."""
        payload = inbound_payload(
            message_id=message_id,
            from_number=from_number,
            text=text,
            profile_name=profile_name,
            phone_number_id=self._phone_number_id,
        )
        body, header = sign(payload, _app_secret())
        response = self._client.post(
            WEBHOOK,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": header,
            },
        )
        assert response.status_code == 200, response.text

    def inbox(self, **params: Any) -> dict[str, Any]:
        response = self._client.get(
            self.path(),
            params=params,
            headers=self.owner_headers,
        )
        assert response.status_code == 200, response.text

        return response.json()


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Business:
    return Business(client, user_repository, membership_repository, "acme-fashion")


@pytest.fixture
def rival(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Business:
    return Business(
        client,
        user_repository,
        membership_repository,
        "rival-store",
        phone_number_id="209876543210987",
    )


@contextmanager
def counting(session: Session) -> Iterator[list[str]]:
    """Record every statement the database is asked to run.

    Attached to the connection the test client shares, so what it counts is
    what a request actually costs.
    """
    statements: list[str] = []
    connection = session.connection()

    def record(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", record)

    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", record)


# --- one row, one request ---------------------------------------------------


def test_an_inbox_row_carries_everything_it_renders(
    client: TestClient,
    acme: Business,
) -> None:
    # The phase's actual requirement: a row names a person, says who has it
    # and shows what was last said, without the client asking again.
    _, agent_id = acme.member("agent@example.com", name="Ali")
    acme.receives("Do you have this in medium?")
    conversation = acme.inbox()["items"][0]
    client.post(
        acme.path(conversation["id"], "/assign"),
        json={"user_id": agent_id},
        headers=acme.owner_headers,
    )

    row = acme.inbox()["items"][0]

    assert row["contact"]["phone_number"] == AYESHA
    assert row["contact"]["name"] == "Ayesha"
    assert row["contact"]["status"] == "lead"
    assert row["assigned_user"] == {
        "id": agent_id,
        "name": "Ali",
        "email": "agent@example.com",
    }
    assert row["last_message"]["text"] == "Do you have this in medium?"
    assert row["last_message"]["sender_type"] == "customer"
    assert row["last_message"]["direction"] == "inbound"
    assert row["last_message_at"] is not None
    assert row["ai_mode"] == "suggest_only"
    assert row["status"] == "open"


def test_a_row_carries_the_newest_message_and_not_the_first(
    client: TestClient,
    acme: Business,
) -> None:
    acme.receives("Do you have this in medium?", message_id="wamid.ONE")
    conversation = acme.inbox()["items"][0]
    client.post(
        acme.path(conversation["id"], "/messages"),
        json={"text": "We do, in navy and black."},
        headers=acme.owner_headers,
    )

    row = acme.inbox()["items"][0]

    assert row["last_message"]["text"] == "We do, in navy and black."
    assert row["last_message"]["sender_type"] == "agent"
    assert row["last_message"]["direction"] == "outbound"


def test_a_long_message_is_cut_down_to_a_preview(
    client: TestClient,
    acme: Business,
) -> None:
    # A row shows one line. Sending four thousand characters of it, thirty
    # times over, is a preview in name only.
    conversation = acme.open()
    client.post(
        acme.path(conversation["id"], "/messages"),
        json={"text": "x" * 4000},
        headers=acme.owner_headers,
    )

    row = acme.inbox()["items"][0]

    assert row["last_message"]["text"] == "x" * PREVIEW_LENGTH


def test_a_thread_with_nothing_said_in_it_has_no_preview(
    client: TestClient,
    acme: Business,
) -> None:
    acme.open()

    row = acme.inbox()["items"][0]

    assert row["last_message"] is None
    assert row["last_message_at"] is None


def test_reading_one_conversation_answers_in_the_same_shape(
    client: TestClient,
    acme: Business,
) -> None:
    # A client that opens a thread should not need a second vocabulary for
    # the object it was just listing.
    acme.receives("Do you have this in medium?")
    listed = acme.inbox()["items"][0]

    read = client.get(acme.path(listed["id"]), headers=acme.owner_headers).json()

    assert read == listed


def test_a_mutation_answers_with_the_whole_row(
    client: TestClient,
    acme: Business,
) -> None:
    # So a dashboard can redraw the row from the response it already has.
    acme.receives("Do you have this in medium?")
    conversation = acme.inbox()["items"][0]

    closed = client.post(
        acme.path(conversation["id"], "/close"),
        headers=acme.owner_headers,
    ).json()

    assert closed["status"] == "closed"
    assert closed["contact"]["phone_number"] == AYESHA
    assert closed["last_message"]["text"] == "Do you have this in medium?"


# --- no N+1 -----------------------------------------------------------------


def test_the_inbox_costs_the_same_whether_it_has_two_rows_or_six(
    client: TestClient,
    db_session: Session,
    acme: Business,
) -> None:
    """The phase's acceptance criterion, as a number rather than a promise.

    Everything a row displays comes from another table -- the contact, the
    assignee, the last message -- so the obvious implementation is three
    more queries per row. This is the test that would catch that: the cost
    of the request must not move when the number of rows does.
    """
    for index, number in enumerate((AYESHA, BILAL)):
        acme.receives(
            "hello",
            from_number=number.removeprefix("+"),
            message_id=f"wamid.FIRST{index}",
        )

    with counting(db_session) as small:
        acme.inbox()

    for index, number in enumerate(("+923005555555", "+923006666666", "+923007777777")):
        acme.receives(
            "hello",
            from_number=number.removeprefix("+"),
            message_id=f"wamid.MORE{index}",
        )
    acme.open(acme.contact("+923008888888"))

    with counting(db_session) as large:
        body = acme.inbox()

    assert body["total"] == 6
    assert len(large) == len(small)
    # Two, and always two: the page and the total behind it. Everything a
    # row displays arrives with the row.
    assert sum("FROM conversations" in statement for statement in large) == 2


# --- the filters an agent reaches for ---------------------------------------


def test_the_inbox_can_be_narrowed_to_several_statuses_at_once(
    client: TestClient,
    acme: Business,
) -> None:
    # The view an inbox opens on. A thread waiting on a delivery is still
    # one somebody has to come back to, so "not closed" is two statuses.
    open_thread = acme.open(acme.contact(AYESHA))
    pending = acme.open(acme.contact(BILAL))
    closed = acme.open(acme.contact("+923005555555"))
    client.patch(
        acme.path(pending["id"]),
        json={"status": "pending"},
        headers=acme.owner_headers,
    )
    client.post(acme.path(closed["id"], "/close"), headers=acme.owner_headers)

    body = acme.inbox(status=["open", "pending"])

    assert body["total"] == 2
    assert {row["id"] for row in body["items"]} == {open_thread["id"], pending["id"]}


def test_mine_is_a_word_rather_than_a_number_the_client_has_to_know(
    client: TestClient,
    acme: Business,
) -> None:
    mine = acme.open(acme.contact(AYESHA))
    theirs = acme.open(acme.contact(BILAL))
    _, agent_id = acme.member("agent@example.com")
    client.post(
        acme.path(mine["id"], "/assign"),
        json={"user_id": acme.owner_id},
        headers=acme.owner_headers,
    )
    client.post(
        acme.path(theirs["id"], "/assign"),
        json={"user_id": agent_id},
        headers=acme.owner_headers,
    )

    body = acme.inbox(assigned_to="me")

    assert body["total"] == 1
    assert body["items"][0]["id"] == mine["id"]


def test_a_colleagues_queue_can_be_asked_for_by_id(
    client: TestClient,
    acme: Business,
) -> None:
    _, agent_id = acme.member("agent@example.com")
    theirs = acme.open(acme.contact(AYESHA))
    acme.open(acme.contact(BILAL))
    client.post(
        acme.path(theirs["id"], "/assign"),
        json={"user_id": agent_id},
        headers=acme.owner_headers,
    )

    body = acme.inbox(assigned_to=str(agent_id))

    assert body["total"] == 1
    assert body["items"][0]["id"] == theirs["id"]


def test_unassigned_is_the_queue_nobody_has_picked_up(
    client: TestClient,
    acme: Business,
) -> None:
    taken = acme.open(acme.contact(AYESHA))
    free = acme.open(acme.contact(BILAL))
    client.post(
        acme.path(taken["id"], "/assign"),
        json={"user_id": acme.owner_id},
        headers=acme.owner_headers,
    )

    body = acme.inbox(unassigned=True)

    assert body["total"] == 1
    assert body["items"][0]["id"] == free["id"]


def test_an_assignee_that_is_neither_me_nor_a_number_is_refused(
    client: TestClient,
    acme: Business,
) -> None:
    response = client.get(
        acme.path(),
        params={"assigned_to": "everyone"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


def test_the_inbox_can_be_narrowed_to_one_contact(
    client: TestClient,
    acme: Business,
) -> None:
    contact_id = acme.contact(AYESHA)
    theirs = acme.open(contact_id)
    acme.open(acme.contact(BILAL))

    body = acme.inbox(contact_id=contact_id)

    assert body["total"] == 1
    assert body["items"][0]["id"] == theirs["id"]


@pytest.mark.parametrize("term", ["ali", "ALI", "Ali"])
def test_searching_finds_a_contact_by_name_whatever_the_case(
    client: TestClient,
    acme: Business,
    term: str,
) -> None:
    wanted = acme.open(acme.contact(AYESHA, name="Ali Raza"))
    acme.open(acme.contact(BILAL, name="Bilal Khan"))

    body = acme.inbox(search=term)

    assert body["total"] == 1
    assert body["items"][0]["id"] == wanted["id"]


def test_searching_finds_a_contact_by_part_of_their_number(
    client: TestClient,
    acme: Business,
) -> None:
    ayesha = acme.open(acme.contact(AYESHA))
    bilal = acme.open(acme.contact(BILAL))

    assert acme.inbox(search="1234567")["items"] == [ayesha]
    assert acme.inbox(search="9876543")["items"] == [bilal]


def test_a_search_total_counts_what_the_search_returns(
    client: TestClient,
    acme: Business,
) -> None:
    # A page and a total that disagree show up as a pagination control
    # promising a page which turns out to be empty.
    for index in range(3):
        acme.open(acme.contact(f"+92300111{index}222", name=f"Ali {index}"))
    acme.open(acme.contact(BILAL, name="Bilal Khan"))

    body = acme.inbox(search="ali", page_size=2)

    assert body["total"] == 3
    assert len(body["items"]) == 2


def test_a_search_never_reaches_another_business(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    rival.open(rival.contact(AYESHA, name="Ali Raza"))

    body = acme.inbox(search="ali")

    assert body["total"] == 0


def test_the_inbox_is_ordered_by_the_last_thing_said(
    client: TestClient,
    acme: Business,
) -> None:
    first = acme.open(acme.contact(AYESHA))
    second = acme.open(acme.contact(BILAL))
    client.post(
        acme.path(first["id"], "/messages"),
        json={"text": "a reply on the older thread"},
        headers=acme.owner_headers,
    )

    body = acme.inbox()

    assert [row["id"] for row in body["items"]] == [first["id"], second["id"]]


# --- unread -----------------------------------------------------------------


def test_a_customers_message_is_unread_until_somebody_says_otherwise(
    client: TestClient,
    acme: Business,
) -> None:
    acme.receives("Do you have this in medium?", message_id="wamid.ONE")

    assert acme.inbox()["items"][0]["unread_count"] == 1

    acme.receives("Hello?", message_id="wamid.TWO")

    row = acme.inbox()["items"][0]
    assert row["unread_count"] == 2
    assert row["last_read_at"] is None


def test_marking_a_thread_read_clears_it_for_the_whole_team(
    client: TestClient,
    acme: Business,
) -> None:
    # For the whole team on purpose: this is a shared inbox, and a badge
    # that stays lit on four other screens after somebody has dealt with a
    # customer is a queue that gets worked four times.
    colleague, _ = acme.member("agent@example.com")
    acme.receives("Do you have this in medium?")
    conversation = acme.inbox()["items"][0]

    marked = client.post(
        acme.path(conversation["id"], "/read"),
        headers=colleague,
    ).json()

    assert marked["unread_count"] == 0
    assert marked["last_read_at"] is not None
    assert acme.inbox()["items"][0]["unread_count"] == 0


def test_marking_a_read_thread_read_again_is_not_an_error(
    client: TestClient,
    acme: Business,
) -> None:
    # So a client can call it whenever a thread is opened, without first
    # working out whether it needs to.
    conversation = acme.open()

    response = client.post(
        acme.path(conversation["id"], "/read"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["unread_count"] == 0


def test_replying_marks_the_thread_read(
    client: TestClient,
    acme: Business,
) -> None:
    # Replying is the strongest statement there is that somebody has read a
    # thread.
    acme.receives("Do you have this in medium?")
    conversation = acme.inbox()["items"][0]
    assert conversation["unread_count"] == 1

    client.post(
        acme.path(conversation["id"], "/messages"),
        json={"text": "We do, in navy and black."},
        headers=acme.owner_headers,
    )

    assert acme.inbox()["items"][0]["unread_count"] == 0


def test_the_teams_own_messages_never_make_a_thread_unread(
    client: TestClient,
    acme: Business,
) -> None:
    # An inbox where answering somebody makes their thread look unattended
    # is one whose badge nobody trusts.
    conversation = acme.open()

    client.post(
        acme.path(conversation["id"], "/messages"),
        json={"text": "Just following up on your order."},
        headers=acme.owner_headers,
    )

    assert acme.inbox()["items"][0]["unread_count"] == 0


def test_a_customer_writing_after_a_reply_is_unread_again(
    client: TestClient,
    acme: Business,
) -> None:
    acme.receives("Do you have this in medium?", message_id="wamid.ONE")
    conversation = acme.inbox()["items"][0]
    client.post(
        acme.path(conversation["id"], "/messages"),
        json={"text": "We do."},
        headers=acme.owner_headers,
    )

    acme.receives("Great, I'll take two.", message_id="wamid.TWO")

    assert acme.inbox()["items"][0]["unread_count"] == 1


def test_a_viewer_may_not_clear_a_badge_their_colleagues_work_from(
    client: TestClient,
    acme: Business,
) -> None:
    headers, _ = acme.member("viewer@example.com", WorkspaceRole.VIEWER)
    conversation = acme.open()

    response = client.post(acme.path(conversation["id"], "/read"), headers=headers)

    assert response.status_code == 403


def test_another_business_cannot_mark_your_thread_read(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    conversation = acme.open()

    response = client.post(
        f"/api/v1/workspaces/{rival.workspace_id}"
        f"/conversations/{conversation['id']}/read",
        headers=rival.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "conversation_not_found"
