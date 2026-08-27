"""Phase 11 acceptance: the assistant, and every way it declines to answer.

The plan's pipeline is deterministic, so its decisions can be tested one
at a time: what happens with no knowledge, with weak evidence, with the
model unavailable, in each of the three AI modes. Those branches are the
whole safety argument, and each of them is a test here.

The model itself is a fake. What is being tested is not whether Claude
writes a good sentence -- this suite cannot know that -- but whether the
pipeline around it grounds, records and withholds correctly.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.support.knowledge import FakeEmbeddingProvider, FakeReplyWriter
from tests.support.whatsapp import PHONE_NUMBER_ID, inbound_payload, sign

PASSWORD = "correct horse battery staple"
WEBHOOK = "/api/v1/webhooks/whatsapp"

RETURNS = (
    "Returns are accepted within 14 days of delivery. The item must be "
    "unworn and in its original packaging."
)


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
    from app.core.config import get_settings

    secret = get_settings().whatsapp_app_secret
    assert secret is not None

    return secret.get_secret_value()


class Business:
    def __init__(self, client: TestClient, slug: str, phone_number_id: str) -> None:
        self._client = client
        self._phone_number_id = phone_number_id

        self.headers = _sign_up(client, f"owner-{slug}@example.com")
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": slug.title(), "slug": slug},
            headers=self.headers,
        ).json()["id"]

        client.post(
            f"/api/v1/workspaces/{self.workspace_id}/integrations/whatsapp/connect",
            json={
                "phone_number": "+15550001111",
                "external_phone_number_id": phone_number_id,
                "access_token": "a-provider-token",
            },
            headers=self.headers,
        )

    def path(self, suffix: str = "") -> str:
        return f"/api/v1/workspaces/{self.workspace_id}{suffix}"

    def knows(self, content: str = RETURNS, title: str = "Returns policy") -> str:
        source = self._client.post(
            self.path("/knowledge/sources"),
            json={"name": "Policies", "source_type": "text"},
            headers=self.headers,
        ).json()["id"]
        response = self._client.post(
            self.path("/knowledge/documents"),
            json={
                "knowledge_source_id": source,
                "title": title,
                "content": content,
            },
            headers=self.headers,
        )
        assert response.status_code == 201, response.text

        return response.json()["id"]

    def thread(self, ai_mode: str = "suggest_only") -> str:
        """Open the thread the customer is about to write into.

        Before the message rather than after it, because an arriving
        message is now what runs the assistant: a mode set afterwards is a
        mode that was not in force when it mattered.
        """
        contact = self._client.post(
            self.path("/contacts"),
            json={"phone_number": "+923001234567"},
            headers=self.headers,
        ).json()["id"]
        conversation = self._client.post(
            self.path("/conversations"),
            json={"contact_id": contact},
            headers=self.headers,
        ).json()["id"]

        if ai_mode != "suggest_only":
            self.mode(conversation, ai_mode)

        return conversation

    def asked(
        self,
        text: str = "Can I return an unworn item within 14 days?",
    ) -> str:
        """A customer writes in, through the real webhook.

        The wording overlaps the stored passage on purpose. The fake
        embedding provider is a bag of words -- see tests/support/knowledge
        -- so a question phrased with none of the passage's vocabulary
        would be testing the provider rather than the pipeline, and this
        suite cannot test the provider.
        """
        payload = inbound_payload(
            message_id=f"wamid.{uuid.uuid4().hex[:12]}",
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

        return self._client.get(
            self.path("/conversations"),
            headers=self.headers,
        ).json()["items"][0]["id"]

    def mode(self, conversation_id: str, ai_mode: str) -> None:
        response = self._client.patch(
            self.path(f"/conversations/{conversation_id}"),
            json={"ai_mode": ai_mode},
            headers=self.headers,
        )
        assert response.status_code == 200, response.text

    def reply(self, conversation_id: str) -> dict[str, Any]:
        response = self._client.post(
            self.path(f"/conversations/{conversation_id}/ai-reply"),
            headers=self.headers,
        )
        assert response.status_code == 200, response.text

        return response.json()

    def log(self, conversation_id: str) -> dict[str, Any]:
        return self._client.get(
            self.path(f"/conversations/{conversation_id}/ai-responses"),
            headers=self.headers,
        ).json()


# Both fakes are installed by the client fixture in conftest, for every
# test. Named again here because these tests read what reached them.
@pytest.fixture
def writer(reply_writer: FakeReplyWriter) -> FakeReplyWriter:
    return reply_writer


@pytest.fixture
def embeddings(embedding_provider: FakeEmbeddingProvider) -> FakeEmbeddingProvider:
    return embedding_provider


@pytest.fixture
def acme(
    client: TestClient,
    writer: FakeReplyWriter,
    embeddings: FakeEmbeddingProvider,
) -> Business:
    return Business(client, "acme-fashion", PHONE_NUMBER_ID)


@pytest.fixture
def rival(
    client: TestClient,
    writer: FakeReplyWriter,
    embeddings: FakeEmbeddingProvider,
) -> Business:
    return Business(client, "rival-store", "209876543210987")


# --- the modes --------------------------------------------------------------


def test_suggest_only_drafts_a_reply_and_sends_nothing(
    client: TestClient,
    acme: Business,
) -> None:
    # Where the plan says pilots start, and the default for a new
    # conversation. A draft for a human to approve.
    acme.knows()
    conversation = acme.thread()

    acme.asked()

    reply = acme.log(conversation)["items"][0]
    assert reply["decision"] == "suggested"
    assert reply["reply_text"]

    thread = client.get(
        acme.path(f"/conversations/{conversation}/messages"),
        headers=acme.headers,
    ).json()
    assert [item["sender_type"] for item in thread["items"]] == ["customer"]


def test_automatic_sends_the_reply_into_the_thread(
    client: TestClient,
    acme: Business,
) -> None:
    acme.knows()
    conversation = acme.thread("automatic")

    acme.asked()

    logged = acme.log(conversation)["items"][0]
    assert logged["decision"] == "answered"

    thread = client.get(
        acme.path(f"/conversations/{conversation}/messages"),
        headers=acme.headers,
    ).json()
    latest = thread["items"][0]
    assert latest["sender_type"] == "ai"
    assert latest["direction"] == "outbound"
    assert latest["text"] == logged["reply_text"]


def test_disabled_refuses_before_anything_is_asked_of_the_model(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    acme.knows()
    conversation = acme.thread("disabled")

    acme.asked()

    logged = acme.log(conversation)["items"][0]
    assert logged["decision"] == "blocked"
    assert logged["reason"] == "ai_disabled"
    assert writer.calls == []

    # And pressing the button once somebody switches it back on does run
    # it: the reason to press it is that something has changed.
    acme.mode(conversation, "suggest_only")
    assert acme.reply(conversation)["decision"] == "suggested"
    assert len(writer.calls) == 1


# --- withholding ------------------------------------------------------------


def test_an_empty_knowledge_base_hands_over_rather_than_guessing(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    # The plan's rule and the reason retrieval comes first: with nothing to
    # ground an answer in, the model is not asked at all.
    conversation = acme.thread()

    acme.asked()

    logged = acme.log(conversation)["items"][0]
    assert logged["decision"] == "handoff"
    assert logged["reason"] == "no_knowledge"
    assert writer.calls == []


def test_a_model_that_says_it_cannot_answer_is_believed(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    acme.knows()
    conversation = acme.thread()
    writer.can_answer = False

    acme.asked()

    logged = acme.log(conversation)["items"][0]
    assert logged["decision"] == "handoff"
    assert logged["reason"] == "cannot_answer"


def test_low_confidence_hands_over_even_with_evidence(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    acme.knows()
    conversation = acme.thread()
    writer.confidence = 0.2

    acme.asked()

    logged = acme.log(conversation)["items"][0]
    assert logged["decision"] == "handoff"
    assert logged["reason"] == "low_confidence"
    # The draft is kept for whoever is tuning the assistant, and the API
    # does not hand it back as something to send.
    assert logged["reply_text"]
    assert acme.reply(conversation)["text"] is None


def test_automatic_mode_cannot_override_a_withheld_reply(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    # The safety argument: whether the reply is fit to send is settled
    # before the mode is consulted, so switching a workspace to automatic
    # cannot send something suggest-only would have withheld.
    acme.knows()
    conversation = acme.thread("automatic")
    writer.confidence = 0.1

    acme.asked()

    logged = acme.log(conversation)["items"][0]
    assert logged["decision"] == "handoff"
    assert logged["sent_message_id"] is None


def test_a_model_outage_never_loses_the_customers_message(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    acme.knows()
    conversation = acme.thread()
    writer.fail_with = "the model is down"

    acme.asked()

    logged = acme.log(conversation)["items"][0]
    assert logged["decision"] == "failed"
    assert logged["reason"] == "provider_error"

    # The question is still there, and still unread, so a person picks it
    # up exactly as they would have if the assistant did not exist.
    thread = client.get(
        acme.path(f"/conversations/{conversation}/messages"),
        headers=acme.headers,
    ).json()
    assert thread["total"] == 1
    assert thread["items"][0]["sender_type"] == "customer"


# --- grounding --------------------------------------------------------------


def test_the_model_is_given_this_businesss_passages_and_no_others(
    client: TestClient,
    acme: Business,
    rival: Business,
    writer: FakeReplyWriter,
) -> None:
    # The plan's "AI cannot access another workspace", checked at the one
    # place it would go wrong: what actually reached the model.
    rival.knows("Rival Store gives refunds for any reason within 90 days.")
    acme.knows()
    acme.thread()

    acme.asked()

    given = " ".join(passage.content for passage in writer.last_passages)
    assert "unworn" in given
    assert "Rival Store" not in given
    assert "90 days" not in given


def test_the_instructions_name_the_business_answering(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    acme.knows()
    acme.thread()

    acme.asked()

    instructions = writer.calls[-1][0]
    assert "Acme-Fashion" in instructions


def test_the_thread_reaches_the_model_oldest_first(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    # The repository returns newest first, which is what a chat screen
    # opens with and the opposite of how a conversation reads.
    acme.knows()
    conversation = acme.thread()
    acme.asked("Can I return an unworn item within 14 days?")
    client.post(
        acme.path(f"/conversations/{conversation}/messages"),
        json={"text": "Let me check that for you."},
        headers=acme.headers,
    )

    acme.asked("And is an unworn item within 14 days refundable?")

    turns = writer.last_turns
    assert [turn.from_customer for turn in turns] == [True, False, True]
    assert turns[0].text == "Can I return an unworn item within 14 days?"
    assert turns[-1].text == "And is an unworn item within 14 days refundable?"


def test_the_sources_behind_an_answer_come_back_with_it(
    client: TestClient,
    acme: Business,
) -> None:
    # What makes a pilot possible: an answer can be checked against the
    # evidence it was grounded in.
    acme.knows()
    conversation = acme.thread()

    acme.asked()

    assert acme.log(conversation)["items"][0]["retrieved_chunk_ids"]


# --- the record -------------------------------------------------------------


def test_every_decision_is_recorded_with_its_prompt_version(
    client: TestClient,
    acme: Business,
) -> None:
    from app.services.prompts import PROMPT_VERSION

    acme.knows()
    conversation = acme.thread()

    acme.asked()

    logged = acme.log(conversation)

    assert logged["total"] == 1

    entry = logged["items"][0]
    assert entry["decision"] == "suggested"
    assert entry["prompt_version"] == PROMPT_VERSION
    assert entry["model"] == "fake-model"
    assert entry["retrieved_chunk_ids"]
    assert entry["confidence"] == 0.9
    assert entry["input_tokens"] == 100
    assert entry["output_tokens"] == 20
    assert entry["latency_ms"] is not None


def test_a_withheld_answer_is_recorded_too(
    client: TestClient,
    acme: Business,
) -> None:
    # The rows worth reading are the ones where it did nothing.
    conversation = acme.thread()

    acme.asked()

    entry = acme.log(conversation)["items"][0]

    assert entry["decision"] == "handoff"
    assert entry["reason"] == "no_knowledge"
    assert entry["reply_text"] is None


def test_the_assistant_answers_one_message_only_once(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    # Reached when a webhook is delivered twice, or when somebody presses
    # the button on a thread already handled. A second reply to one
    # customer message is worse than none.
    acme.knows()
    conversation = acme.thread("automatic")

    acme.asked()

    # Pressing the button afterwards must not answer again: that reply
    # reached the customer, and a second one is their phone buzzing twice
    # with two different answers.
    first = acme.reply(conversation)
    second = acme.reply(conversation)

    assert first["decision"] == second["decision"] == "answered"
    assert first["message_id"] == second["message_id"] is not None
    assert len(writer.calls) == 1
    assert acme.log(conversation)["total"] == 1

    thread = client.get(
        acme.path(f"/conversations/{conversation}/messages"),
        headers=acme.headers,
    ).json()
    assert [item["sender_type"] for item in thread["items"]].count("ai") == 1


# --- the boundary -----------------------------------------------------------


def test_another_business_cannot_ask_your_conversation_for_a_reply(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    acme.knows()
    conversation = acme.asked()

    response = client.post(
        rival.path(f"/conversations/{conversation}/ai-reply"),
        headers=rival.headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "conversation_not_found"


def test_another_business_cannot_read_your_assistants_history(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    acme.knows()
    conversation = acme.asked()
    acme.reply(conversation)

    body = client.get(
        rival.path(f"/conversations/{conversation}/ai-responses"),
        headers=rival.headers,
    ).json()

    assert body["total"] == 0


def test_a_viewer_may_read_the_history_but_not_run_the_assistant(
    client: TestClient,
    acme: Business,
) -> None:
    from app.models.workspace_membership import WorkspaceRole
    from app.repositories.workspace_membership_repository import (
        WorkspaceMembershipRepository,
    )

    acme.knows()
    conversation = acme.asked()

    headers = _sign_up(client, "viewer@example.com")
    user = client.get("/api/v1/auth/me", headers=headers).json()
    # Reaching for the repository directly rather than through an
    # invitation: this test is about the role, not about how somebody got
    # it.
    from app.db.session import get_db_session

    session = client.app.dependency_overrides[get_db_session]()  # type: ignore[attr-defined]
    WorkspaceMembershipRepository(session).create(
        workspace_id=uuid.UUID(acme.workspace_id),
        user_id=user["id"],
        role=WorkspaceRole.VIEWER,
    )
    session.commit()

    assert (
        client.post(
            acme.path(f"/conversations/{conversation}/ai-reply"),
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.get(
            acme.path(f"/conversations/{conversation}/ai-responses"),
            headers=headers,
        ).status_code
        == 200
    )


def test_the_assistant_requires_a_token(client: TestClient, acme: Business) -> None:
    conversation = acme.asked()

    assert (
        client.post(acme.path(f"/conversations/{conversation}/ai-reply")).status_code
        == 401
    )


def test_a_delivery_failure_still_answers_and_keeps_the_reply(
    client: TestClient,
    acme: Business,
    messaging_provider,
) -> None:
    # WhatsApp being down is not the assistant failing. The reply is in
    # the thread marked failed, so an agent can see what it said and that
    # it did not go.
    acme.knows()
    conversation = acme.thread("automatic")
    messaging_provider.fail_with = "Meta is unavailable"

    acme.asked()

    logged = acme.log(conversation)["items"][0]
    assert logged["decision"] == "answered"
    assert logged["sent_message_id"] is None

    thread = client.get(
        acme.path(f"/conversations/{conversation}/messages"),
        headers=acme.headers,
    ).json()
    latest = thread["items"][0]
    assert latest["sender_type"] == "ai"
    assert latest["status"] == "failed"
    assert latest["text"] == logged["reply_text"]


# --- the assistant runs on its own ------------------------------------------


def test_an_inbound_message_is_answered_without_anybody_asking(
    client: TestClient,
    acme: Business,
) -> None:
    # The plan's pipeline starts at "inbound message", and automatic mode
    # means nothing if a person still has to press the button.
    acme.knows()
    first = acme.asked()
    acme.mode(first, "automatic")

    # A second message on the same thread, now that automatic is on.
    acme.asked("And is delivery within 14 days free?")

    thread = client.get(
        acme.path(f"/conversations/{first}/messages"),
        headers=acme.headers,
    ).json()

    assert [item["sender_type"] for item in thread["items"]].count("ai") == 1


def test_a_repeated_delivery_does_not_produce_a_repeated_answer(
    client: TestClient,
    acme: Business,
    writer: FakeReplyWriter,
) -> None:
    # Meta resends an envelope whenever it does not get a prompt 200,
    # including when it did and the response was lost. Answering twice
    # would be the customer's phone buzzing twice.
    acme.knows()
    conversation = acme.thread("automatic")

    payload = inbound_payload(
        message_id="wamid.REPEATED",
        text="Can I return an unworn item within 14 days?",
        phone_number_id=PHONE_NUMBER_ID,
    )
    body, header = sign(payload, _app_secret())
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": header,
    }

    for _ in range(3):
        assert client.post(WEBHOOK, content=body, headers=headers).status_code == 200

    assert len(writer.calls) == 1

    thread = client.get(
        acme.path(f"/conversations/{conversation}/messages"),
        headers=acme.headers,
    ).json()
    assert [item["sender_type"] for item in thread["items"]].count("ai") == 1


def test_suggest_only_answers_nothing_when_a_message_arrives(
    client: TestClient,
    acme: Business,
) -> None:
    # The default. A draft is recorded for a human; nothing is sent.
    acme.knows()
    conversation = acme.asked()

    thread = client.get(
        acme.path(f"/conversations/{conversation}/messages"),
        headers=acme.headers,
    ).json()
    assert [item["sender_type"] for item in thread["items"]] == ["customer"]

    logged = acme.log(conversation)
    assert logged["total"] == 1
    assert logged["items"][0]["decision"] == "suggested"
