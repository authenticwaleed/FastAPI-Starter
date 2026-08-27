"""Phase 12 acceptance: giving humans control over the automation.

The plan calls this mandatory for a serious support product, and its
business rule is one sentence: once a human takes over, the AI must not
continue automatically replying unless explicitly released. Most of this
file is that sentence, checked from each direction -- the mode, the next
inbound message, the release, and the record of who did what.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.workspace_membership import WorkspaceRole
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from tests.support.knowledge import FakeReplyWriter
from tests.support.whatsapp import PHONE_NUMBER_ID, inbound_payload, sign

PASSWORD = "correct horse battery staple"
WEBHOOK = "/api/v1/webhooks/whatsapp"
CUSTOMER = "+923001234567"

RETURNS = (
    "Returns are accepted within 14 days of delivery. The item must be "
    "unworn and in its original packaging."
)
QUESTION = "Can I return an unworn item within 14 days?"


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


def _app_secret() -> str:
    secret = get_settings().whatsapp_app_secret
    assert secret is not None

    return secret.get_secret_value()


class Business:
    def __init__(
        self,
        client: TestClient,
        memberships: WorkspaceMembershipRepository,
        slug: str,
        phone_number_id: str = PHONE_NUMBER_ID,
    ) -> None:
        self._client = client
        self._memberships = memberships
        self._phone_number_id = phone_number_id

        self.headers = _sign_up(client, f"owner-{slug}@example.com")
        self.owner_id = client.get("/api/v1/auth/me", headers=self.headers).json()["id"]
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": slug.title(), "slug": slug},
            headers=self.headers,
        ).json()["id"]

        client.post(
            self.path("/integrations/whatsapp/connect"),
            json={
                "phone_number": "+15550001111",
                "external_phone_number_id": phone_number_id,
                "access_token": "a-provider-token",
            },
            headers=self.headers,
        )

    def path(self, suffix: str = "") -> str:
        return f"/api/v1/workspaces/{self.workspace_id}{suffix}"

    def member(self, email: str, role: WorkspaceRole) -> tuple[dict[str, str], int]:
        headers = _sign_up(self._client, email)
        user_id = self._client.get("/api/v1/auth/me", headers=headers).json()["id"]
        self._memberships.create(
            workspace_id=uuid.UUID(self.workspace_id),
            user_id=user_id,
            role=role,
        )

        return headers, user_id

    def knows(self, content: str = RETURNS) -> None:
        source = self._client.post(
            self.path("/knowledge/sources"),
            json={"name": "Policies", "source_type": "text"},
            headers=self.headers,
        ).json()["id"]
        response = self._client.post(
            self.path("/knowledge/documents"),
            json={
                "knowledge_source_id": source,
                "title": "Returns policy",
                "content": content,
            },
            headers=self.headers,
        )
        assert response.status_code == 201, response.text

    def thread(self, ai_mode: str = "suggest_only") -> str:
        contact = self._client.post(
            self.path("/contacts"),
            json={"phone_number": CUSTOMER},
            headers=self.headers,
        ).json()["id"]
        conversation = self._client.post(
            self.path("/conversations"),
            json={"contact_id": contact},
            headers=self.headers,
        ).json()["id"]

        if ai_mode != "suggest_only":
            response = self._client.patch(
                self.path(f"/conversations/{conversation}"),
                json={"ai_mode": ai_mode},
                headers=self.headers,
            )
            assert response.status_code == 200, response.text

        return conversation

    def asked(self, text: str = QUESTION, message_id: str | None = None) -> None:
        payload = inbound_payload(
            message_id=message_id or f"wamid.{uuid.uuid4().hex[:12]}",
            text=text,
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

    def read(self, conversation: str, headers: dict[str, str] | None = None) -> Any:
        return self._client.get(
            self.path(f"/conversations/{conversation}"),
            headers=headers or self.headers,
        ).json()

    def events(self, conversation: str) -> Any:
        return self._client.get(
            self.path(f"/conversations/{conversation}/events"),
            headers=self.headers,
        ).json()

    def messages(self, conversation: str) -> Any:
        return self._client.get(
            self.path(f"/conversations/{conversation}/messages"),
            headers=self.headers,
        ).json()


@pytest.fixture
def writer(reply_writer: FakeReplyWriter) -> FakeReplyWriter:
    return reply_writer


@pytest.fixture
def acme(
    client: TestClient,
    membership_repository: WorkspaceMembershipRepository,
    writer: FakeReplyWriter,
) -> Business:
    return Business(client, membership_repository, "acme-fashion")


@pytest.fixture
def rival(
    client: TestClient,
    membership_repository: WorkspaceMembershipRepository,
    writer: FakeReplyWriter,
) -> Business:
    return Business(client, membership_repository, "rival-store", "209876543210987")


# --- taking over ------------------------------------------------------------


def test_taking_over_stops_the_assistant_and_claims_the_thread(
    client: TestClient,
    acme: Business,
) -> None:
    acme.knows()
    conversation = acme.thread("automatic")

    taken = client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={"reason": "customer asked for a person"},
        headers=acme.headers,
    )

    assert taken.status_code == 200

    body = taken.json()
    assert body["state"] == "human_active"
    assert body["ai_mode"] == "disabled"
    assert body["handoff_at"] is not None
    assert body["handoff_reason"] == "customer asked for a person"
    assert body["handoff_by_user_id"] == acme.owner_id
    # Claimed as well as taken: switching the assistant off and leaving
    # nobody looking is worse for the customer than either alternative.
    assert body["assigned_user"]["id"] == acme.owner_id


def test_the_assistant_does_not_answer_after_a_takeover(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    # The plan's business rule, checked where it actually matters: the
    # next message the customer sends.
    acme.knows()
    conversation = acme.thread("automatic")
    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={"reason": "handling this myself"},
        headers=acme.headers,
    )
    writer.calls.clear()

    acme.asked()

    assert writer.calls == []
    assert [item["sender_type"] for item in acme.messages(conversation)["items"]] == [
        "customer"
    ]


def test_a_takeover_needs_no_reason(client: TestClient, acme: Business) -> None:
    conversation = acme.thread()

    response = client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={},
        headers=acme.headers,
    )

    assert response.status_code == 200
    assert response.json()["handoff_reason"] is None


def test_taking_over_twice_is_not_an_error(client: TestClient, acme: Business) -> None:
    conversation = acme.thread()
    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={"reason": "first"},
        headers=acme.headers,
    )

    second = client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={"reason": "second"},
        headers=acme.headers,
    )

    assert second.status_code == 200
    # The latest reason wins, which is what a colleague taking a thread
    # from another colleague expects.
    assert second.json()["handoff_reason"] == "second"


# --- releasing --------------------------------------------------------------


def test_releasing_hands_the_thread_back(client: TestClient, acme: Business) -> None:
    acme.knows()
    conversation = acme.thread("automatic")
    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={"reason": "mine"},
        headers=acme.headers,
    )

    released = client.post(
        acme.path(f"/conversations/{conversation}/release-to-ai"),
        json={},
        headers=acme.headers,
    )

    assert released.status_code == 200

    body = released.json()
    assert body["state"] == "suggest_only"
    assert body["handoff_at"] is None
    assert body["handoff_reason"] is None
    assert body["handoff_by_user_id"] is None
    # The assignment survives: releasing the assistant and dropping the
    # thread are two decisions.
    assert body["assigned_user"]["id"] == acme.owner_id


def test_releasing_can_put_it_straight_back_on_automatic(
    client: TestClient,
    acme: Business,
) -> None:
    conversation = acme.thread("automatic")
    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={},
        headers=acme.headers,
    )

    released = client.post(
        acme.path(f"/conversations/{conversation}/release-to-ai"),
        json={"ai_mode": "automatic"},
        headers=acme.headers,
    )

    assert released.json()["state"] == "ai_active"


def test_the_assistant_answers_again_once_released(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    acme.knows()
    conversation = acme.thread("automatic")
    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={},
        headers=acme.headers,
    )
    client.post(
        acme.path(f"/conversations/{conversation}/release-to-ai"),
        json={"ai_mode": "automatic"},
        headers=acme.headers,
    )
    writer.calls.clear()

    acme.asked()

    assert len(writer.calls) == 1
    assert "ai" in [
        item["sender_type"] for item in acme.messages(conversation)["items"]
    ]


# --- the assistant handing over on its own ----------------------------------


def test_the_assistant_hands_over_when_it_cannot_answer(
    client: TestClient,
    acme: Business,
) -> None:
    # No knowledge base at all, so there is nothing to ground an answer in.
    conversation = acme.thread("automatic")

    acme.asked()

    body = acme.read(conversation)
    assert body["state"] == "human_active"
    assert body["handoff_reason"] == "no_knowledge"
    # Nobody has claimed it, which is what puts it in the unassigned queue
    # rather than quietly on somebody's list.
    assert body["handoff_by_user_id"] is None
    assert body["assigned_user"] is None


def test_the_assistants_handoff_leaves_the_workspaces_mode_alone(
    client: TestClient,
    acme: Business,
) -> None:
    # One question the knowledge base could not cover is not grounds for
    # silently rewriting a setting the business chose.
    conversation = acme.thread("automatic")

    acme.asked()

    assert acme.read(conversation)["ai_mode"] == "automatic"


def test_the_assistant_stops_after_handing_over(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    conversation = acme.thread("automatic")
    acme.asked()
    writer.calls.clear()

    # The knowledge arrives after the handoff. The assistant still stays
    # out until somebody releases it: a thread waiting for a person is not
    # one to start answering into unannounced.
    acme.knows()
    acme.asked("And is an unworn item within 14 days refundable?")

    assert writer.calls == []
    assert acme.read(conversation)["state"] == "human_active"


def test_an_agent_can_still_ask_for_a_draft_on_a_handed_over_thread(
    client: TestClient,
    acme: Business,
) -> None:
    # Pressing the button is an explicit request from a person, which is a
    # different thing from the assistant deciding to speak.
    acme.knows()
    conversation = acme.thread()
    acme.asked()
    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={},
        headers=acme.headers,
    )
    client.post(
        acme.path(f"/conversations/{conversation}/release-to-ai"),
        json={},
        headers=acme.headers,
    )

    reply = client.post(
        acme.path(f"/conversations/{conversation}/ai-reply"),
        headers=acme.headers,
    ).json()

    assert reply["decision"] == "suggested"
    assert reply["text"]


# --- the audit trail --------------------------------------------------------


def test_every_change_of_hands_is_recorded(
    client: TestClient,
    acme: Business,
) -> None:
    conversation = acme.thread("automatic")
    acme.asked()
    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={"reason": "customer is upset"},
        headers=acme.headers,
    )
    client.post(
        acme.path(f"/conversations/{conversation}/release-to-ai"),
        json={},
        headers=acme.headers,
    )

    trail = acme.events(conversation)

    assert trail["total"] == 3
    assert [item["event_type"] for item in trail["items"]] == [
        "ai_released",
        "human_takeover",
        "ai_handoff",
    ]

    handoff = trail["items"][-1]
    assert handoff["reason"] == "no_knowledge"
    # Null means the assistant did it: the only actor here that is not a
    # person.
    assert handoff["actor_user_id"] is None

    takeover = trail["items"][1]
    assert takeover["actor_user_id"] == acme.owner_id
    assert takeover["reason"] == "customer is upset"


def test_the_trail_says_which_colleague_took_a_thread(
    client: TestClient,
    acme: Business,
) -> None:
    headers, agent_id = acme.member("agent@example.com", WorkspaceRole.AGENT)
    conversation = acme.thread()

    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={"reason": "I know this customer"},
        headers=headers,
    )

    latest = acme.events(conversation)["items"][0]
    assert latest["event_type"] == "human_takeover"
    assert latest["actor_user_id"] == agent_id
    assert acme.read(conversation)["handoff_by_user_id"] == agent_id


# --- who may do what --------------------------------------------------------


def test_a_viewer_may_read_the_trail_but_not_take_a_thread(
    client: TestClient,
    acme: Business,
) -> None:
    headers, _ = acme.member("viewer@example.com", WorkspaceRole.VIEWER)
    conversation = acme.thread()

    assert (
        client.post(
            acme.path(f"/conversations/{conversation}/takeover"),
            json={},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            acme.path(f"/conversations/{conversation}/release-to-ai"),
            json={},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.get(
            acme.path(f"/conversations/{conversation}/events"),
            headers=headers,
        ).status_code
        == 200
    )


@pytest.mark.parametrize("suffix", ["/takeover", "/release-to-ai"])
def test_another_business_cannot_take_your_thread(
    client: TestClient,
    acme: Business,
    rival: Business,
    suffix: str,
) -> None:
    conversation = acme.thread()

    response = client.post(
        rival.path(f"/conversations/{conversation}{suffix}"),
        json={},
        headers=rival.headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "conversation_not_found"


def test_another_business_cannot_read_your_trail(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    conversation = acme.thread()
    client.post(
        acme.path(f"/conversations/{conversation}/takeover"),
        json={},
        headers=acme.headers,
    )

    response = client.get(
        rival.path(f"/conversations/{conversation}/events"),
        headers=rival.headers,
    )

    assert response.status_code == 404
