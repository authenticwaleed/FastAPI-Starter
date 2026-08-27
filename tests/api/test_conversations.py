"""Phase 6 acceptance: the inbox API, end to end."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.workspace_membership import WorkspaceRole
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)

PASSWORD = "correct horse battery staple"
NUMBER = "+923001234567"
OTHER_NUMBER = "+923009876543"

OWNER = WorkspaceRole.OWNER
ADMIN = WorkspaceRole.ADMIN
AGENT = WorkspaceRole.AGENT
VIEWER = WorkspaceRole.VIEWER


def _sign_up(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"name": "Someone", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


class Business:
    def __init__(
        self,
        client: TestClient,
        users: UserRepository,
        memberships: WorkspaceMembershipRepository,
        slug: str,
    ) -> None:
        self._client = client
        self._users = users
        self._memberships = memberships

        self.owner_headers = _sign_up(client, f"owner-{slug}@example.com")
        self.owner_id = self._user_id(f"owner-{slug}@example.com")
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": slug.title(), "slug": slug},
            headers=self.owner_headers,
        ).json()["id"]

    def _user_id(self, email: str) -> int:
        user = self._users.get_by_email(email)
        assert user is not None

        return user.id

    def member(self, email: str, role: WorkspaceRole) -> tuple[dict[str, str], int]:
        headers = _sign_up(self._client, email)
        user_id = self._user_id(email)
        self._memberships.create(
            workspace_id=uuid.UUID(self.workspace_id),
            user_id=user_id,
            role=role,
        )

        return headers, user_id

    def contact(self, number: str = NUMBER) -> str:
        return self._client.post(
            f"/api/v1/workspaces/{self.workspace_id}/contacts",
            json={"phone_number": number},
            headers=self.owner_headers,
        ).json()["id"]

    def path(self, conversation_id: str | None = None, suffix: str = "") -> str:
        base = f"/api/v1/workspaces/{self.workspace_id}/conversations"

        if conversation_id is None:
            return base

        return f"{base}/{conversation_id}{suffix}"

    def open(
        self, contact_id: str | None = None, headers: dict[str, str] | None = None
    ):
        return self._client.post(
            self.path(),
            json={"contact_id": contact_id or self.contact()},
            headers=headers or self.owner_headers,
        )


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
    return Business(client, user_repository, membership_repository, "rival-store")


# --- opening ----------------------------------------------------------------


def test_opening_a_conversation_returns_201(
    client: TestClient,
    acme: Business,
) -> None:
    response = acme.open()

    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "open"
    assert body["channel"] == "whatsapp"
    assert body["ai_mode"] == "suggest_only"
    assert body["assigned_user"] is None
    assert body["last_message"] is None
    assert body["last_message_at"] is None
    assert body["unread_count"] == 0
    assert body["contact"]["phone_number"] == NUMBER


def test_a_second_live_conversation_with_one_contact_is_a_409(
    client: TestClient,
    acme: Business,
) -> None:
    contact_id = acme.contact()
    acme.open(contact_id)

    response = acme.open(contact_id)

    assert response.status_code == 409
    assert response.json()["code"] == "conversation_already_open"


def test_a_contact_from_another_business_is_a_404(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    theirs = rival.contact()

    response = acme.open(theirs)

    assert response.status_code == 404
    assert response.json()["code"] == "contact_not_found"


# --- reading ----------------------------------------------------------------


def test_a_conversation_can_be_read_back(
    client: TestClient,
    acme: Business,
) -> None:
    created = acme.open().json()

    response = client.get(acme.path(created["id"]), headers=acme.owner_headers)

    assert response.status_code == 200
    assert response.json() == created


def test_the_inbox_is_paginated(client: TestClient, acme: Business) -> None:
    for number in (NUMBER, OTHER_NUMBER, "+923005555555"):
        acme.open(acme.contact(number))

    body = client.get(
        acme.path(),
        params={"page": 1, "page_size": 2},
        headers=acme.owner_headers,
    ).json()

    assert len(body["items"]) == 2
    assert body["total"] == 3


def test_the_inbox_can_be_filtered(client: TestClient, acme: Business) -> None:
    first = acme.open(acme.contact(NUMBER)).json()
    acme.open(acme.contact(OTHER_NUMBER))
    client.post(acme.path(first["id"], "/close"), headers=acme.owner_headers)

    closed = client.get(
        acme.path(), params={"status": "closed"}, headers=acme.owner_headers
    ).json()

    assert closed["total"] == 1
    assert closed["items"][0]["id"] == first["id"]


def test_an_unknown_conversation_is_a_404(
    client: TestClient,
    acme: Business,
) -> None:
    response = client.get(acme.path(str(uuid.uuid4())), headers=acme.owner_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "conversation_not_found"


# --- assignment, closing, reopening -----------------------------------------


def test_a_conversation_can_be_assigned_and_unassigned(
    client: TestClient,
    acme: Business,
) -> None:
    _, agent_id = acme.member("agent@example.com", AGENT)
    created = acme.open().json()

    assigned = client.post(
        acme.path(created["id"], "/assign"),
        json={"user_id": agent_id},
        headers=acme.owner_headers,
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_user"] == {
        "id": agent_id,
        "name": "Someone",
        "email": "agent@example.com",
    }

    cleared = client.post(
        acme.path(created["id"], "/assign"),
        json={"user_id": None},
        headers=acme.owner_headers,
    )
    assert cleared.json()["assigned_user"] is None


def test_a_conversation_cannot_be_assigned_outside_the_workspace(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    created = acme.open().json()

    response = client.post(
        acme.path(created["id"], "/assign"),
        json={"user_id": rival.owner_id},
        headers=acme.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "membership_not_found"


def test_closing_and_reopening(client: TestClient, acme: Business) -> None:
    created = acme.open().json()

    closed = client.post(
        acme.path(created["id"], "/close"), headers=acme.owner_headers
    ).json()
    assert closed["status"] == "closed"
    assert closed["closed_at"] is not None

    reopened = client.post(
        acme.path(created["id"], "/reopen"), headers=acme.owner_headers
    ).json()
    assert reopened["status"] == "open"
    assert reopened["closed_at"] is None


def test_closing_twice_is_not_an_error(client: TestClient, acme: Business) -> None:
    created = acme.open().json()
    client.post(acme.path(created["id"], "/close"), headers=acme.owner_headers)

    response = client.post(
        acme.path(created["id"], "/close"), headers=acme.owner_headers
    )

    assert response.status_code == 200


def test_reopening_is_refused_if_a_newer_thread_took_its_place(
    client: TestClient,
    acme: Business,
) -> None:
    contact_id = acme.contact()
    first = acme.open(contact_id).json()
    client.post(acme.path(first["id"], "/close"), headers=acme.owner_headers)
    acme.open(contact_id)

    response = client.post(
        acme.path(first["id"], "/reopen"), headers=acme.owner_headers
    )

    assert response.status_code == 409
    assert response.json()["code"] == "conversation_already_open"


def test_the_ai_mode_can_be_changed(client: TestClient, acme: Business) -> None:
    created = acme.open().json()

    response = client.patch(
        acme.path(created["id"]),
        json={"ai_mode": "disabled"},
        headers=acme.owner_headers,
    )

    assert response.json()["ai_mode"] == "disabled"


def test_an_invented_status_is_rejected(client: TestClient, acme: Business) -> None:
    created = acme.open().json()

    response = client.patch(
        acme.path(created["id"]),
        json={"status": "archived"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


# --- messages ---------------------------------------------------------------


def test_sending_a_reply_returns_201(client: TestClient, acme: Business) -> None:
    created = acme.open().json()

    response = client.post(
        acme.path(created["id"], "/messages"),
        json={"text": "Hello, how can I help?"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 201

    body = response.json()
    assert body["text"] == "Hello, how can I help?"
    assert body["sender_type"] == "agent"
    assert body["direction"] == "outbound"
    assert body["status"] == "queued"
    assert body["content_type"] == "text"


def test_a_thread_reads_back_newest_first(
    client: TestClient,
    acme: Business,
) -> None:
    created = acme.open().json()
    for index in range(3):
        client.post(
            acme.path(created["id"], "/messages"),
            json={"text": f"line {index}"},
            headers=acme.owner_headers,
        )

    body = client.get(
        acme.path(created["id"], "/messages"), headers=acme.owner_headers
    ).json()

    assert body["total"] == 3
    assert [item["text"] for item in body["items"]] == ["line 2", "line 1", "line 0"]


def test_sending_moves_the_conversation_up_the_inbox(
    client: TestClient,
    acme: Business,
) -> None:
    created = acme.open().json()
    client.post(
        acme.path(created["id"], "/messages"),
        json={"text": "hello"},
        headers=acme.owner_headers,
    )

    read = client.get(acme.path(created["id"]), headers=acme.owner_headers).json()

    assert read["last_message_at"] is not None


def test_a_closed_conversation_refuses_a_reply(
    client: TestClient,
    acme: Business,
) -> None:
    created = acme.open().json()
    client.post(acme.path(created["id"], "/close"), headers=acme.owner_headers)

    response = client.post(
        acme.path(created["id"], "/messages"),
        json={"text": "are you there?"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "conversation_closed"


def test_an_empty_message_is_rejected(client: TestClient, acme: Business) -> None:
    created = acme.open().json()

    response = client.post(
        acme.path(created["id"], "/messages"),
        json={"text": ""},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


def test_a_message_longer_than_whatsapp_allows_is_rejected(
    client: TestClient,
    acme: Business,
) -> None:
    created = acme.open().json()

    response = client.post(
        acme.path(created["id"], "/messages"),
        json={"text": "x" * 4097},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


# --- who may do what --------------------------------------------------------


@pytest.mark.parametrize("role", [OWNER, ADMIN, AGENT, VIEWER])
def test_every_member_may_read_the_inbox(
    client: TestClient,
    acme: Business,
    role: WorkspaceRole,
) -> None:
    headers, _ = acme.member(f"{role.value}@example.com", role)
    created = acme.open().json()

    assert client.get(acme.path(), headers=headers).status_code == 200
    assert client.get(acme.path(created["id"]), headers=headers).status_code == 200
    assert (
        client.get(acme.path(created["id"], "/messages"), headers=headers).status_code
        == 200
    )


def test_an_agent_may_reply_and_take_over(
    client: TestClient,
    acme: Business,
) -> None:
    # The plan gives an agent exactly this: view conversations, send
    # messages, take over conversations.
    headers, agent_id = acme.member("agent@example.com", AGENT)
    created = acme.open().json()

    assert (
        client.post(
            acme.path(created["id"], "/messages"),
            json={"text": "I will take this"},
            headers=headers,
        ).status_code
        == 201
    )
    assert (
        client.post(
            acme.path(created["id"], "/assign"),
            json={"user_id": agent_id},
            headers=headers,
        ).status_code
        == 200
    )


def test_a_viewer_may_look_and_nothing_else(
    client: TestClient,
    acme: Business,
) -> None:
    headers, _ = acme.member("viewer@example.com", VIEWER)
    created = acme.open().json()

    assert acme.open(acme.contact(OTHER_NUMBER), headers=headers).status_code == 403
    assert (
        client.post(
            acme.path(created["id"], "/messages"),
            json={"text": "hello"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(acme.path(created["id"], "/close"), headers=headers).status_code
        == 403
    )


# --- the tenant boundary ----------------------------------------------------


@pytest.mark.parametrize("method", ["get", "post"])
def test_the_inbox_requires_a_token(
    client: TestClient,
    acme: Business,
    method: str,
) -> None:
    response = client.request(method, acme.path(), json={"contact_id": acme.contact()})

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("get", ""), ("patch", ""), ("get", "/messages"), ("post", "/messages")],
)
def test_another_business_cannot_reach_your_conversation(
    client: TestClient,
    acme: Business,
    rival: Business,
    method: str,
    suffix: str,
) -> None:
    created = acme.open().json()

    response = client.request(
        method,
        f"/api/v1/workspaces/{rival.workspace_id}/conversations/{created['id']}{suffix}",
        json={"text": "who are you", "ai_mode": "disabled"},
        headers=rival.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "conversation_not_found"


def test_another_businesss_conversations_never_appear_in_your_inbox(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    acme.open()
    rival.open()

    body = client.get(acme.path(), headers=acme.owner_headers).json()

    assert body["total"] == 1
