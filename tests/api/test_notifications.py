"""Phase 23: what a person is told, and who is allowed to be told it.

The endpoints have no workspace in their path, which is the plan's list
read literally and also the right shape: a notification is addressed to a
person, and a person opening theirs wants everything meant for them. What
keeps the tenant boundary is the recipient plus a membership check on
every read.
"""

import uuid
from datetime import datetime
from itertools import count

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.conversation import AiMode, Channel
from app.models.message import Direction, MessageStatus, SenderType
from app.models.workspace_membership import MembershipStatus, WorkspaceRole
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from tests.support.knowledge import FakeEmbeddingProvider
from tests.support.messaging import FakeMessagingProvider
from tests.support.tenants import Tenant

FEED = "/api/v1/notifications"


@pytest.fixture
def notification_repository(db_session: Session) -> NotificationRepository:
    return NotificationRepository(db_session)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _connected(
    tenant: Tenant,
    accounts: WhatsAppAccountRepository,
    session: Session,
) -> None:
    from app.core.encryption import encrypt

    accounts.create(
        workspace_id=uuid.UUID(tenant.workspace_id),
        provider="meta_cloud",  # type: ignore[arg-type]
        phone_number="+15550001111",
        external_phone_number_id=f"pnid-{tenant.workspace_id[:8]}",
        external_business_account_id=None,
        access_token_encrypted=encrypt("a-provider-token"),
    )
    session.flush()


def _feed(client: TestClient, headers: dict[str, str], **params: object) -> dict:
    return client.get(FEED, params=params, headers=headers).json()


def _unread(client: TestClient, headers: dict[str, str], **params: object) -> int:
    return client.get(
        f"{FEED}/unread-count",
        params=params,
        headers=headers,
    ).json()["unread"]


def _assign(tenant: Tenant, conversation_id: str, user_id: int) -> None:
    response = tenant.client.post(
        tenant.path("conversations", conversation_id, "assign"),
        json={"user_id": user_id},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 200, response.text


_numbers = count(1)


def _thread(tenant: Tenant) -> str:
    """A conversation with a customer nobody else in this test has.

    A fresh number each time, because a workspace holds one contact per
    phone number -- and every test here that wants two threads wants two
    customers rather than a 409.
    """
    contact = tenant.contact(f"+92300{next(_numbers):07d}")

    return tenant.client.post(
        tenant.path("conversations"),
        json={"contact_id": contact},
        headers=tenant.owner_headers,
    ).json()["id"]


def _asked(
    tenant: Tenant,
    messages: MessageRepository,
    conversations: ConversationRepository,
    session: Session,
) -> str:
    """A thread with a customer question in it, for the assistant to read.

    Written to the table rather than posted, because the messages
    endpoint records what an agent typed -- outbound -- and the assistant
    only answers a customer.
    """
    conversation = _thread(tenant)
    messages.create(
        workspace_id=uuid.UUID(tenant.workspace_id),
        conversation_id=uuid.UUID(conversation),
        sender_type=SenderType.CUSTOMER,
        direction=Direction.INBOUND,
        channel=Channel.WHATSAPP,
        status=MessageStatus.DELIVERED,
        text="do you deliver on Sundays?",
    )
    session.flush()

    return conversation


def _user_id(users: UserRepository, email: str) -> int:
    user = users.get_by_email(email)
    assert user is not None

    return user.id


# --- being told something -------------------------------------------------


def test_being_assigned_a_conversation_is_worth_telling_somebody(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    conversation = _thread(acme)

    _assign(acme, conversation, _user_id(user_repository, "agent@example.com"))

    feed = _feed(acme.client, agent)
    assert feed["total"] == 1
    assert feed["items"][0]["kind"] == "conversation_assigned"
    assert feed["items"][0]["metadata"]["conversation_id"] == conversation
    assert feed["items"][0]["workspace_id"] == acme.workspace_id


def test_nobody_is_told_they_assigned_something_to_themselves(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    # They already know, and a badge for their own click is noise.
    conversation = _thread(acme)

    _assign(
        acme,
        conversation,
        _user_id(user_repository, "owner-acme-fashion@example.com"),
    )

    assert _feed(acme.client, acme.owner_headers)["total"] == 0


def test_unassigning_tells_nobody(acme: Tenant) -> None:
    conversation = _thread(acme)

    acme.client.post(
        acme.path("conversations", conversation, "assign"),
        json={"user_id": None},
        headers=acme.owner_headers,
    )

    assert _feed(acme.client, acme.owner_headers)["total"] == 0


def test_a_handoff_tells_everybody_who_handles_customers(
    acme: Tenant,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    # Nobody has claimed it, so a thread the assistant could not answer is
    # exactly the thing that goes unnoticed until a customer gives up.
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    viewer = acme.member("viewer@example.com", WorkspaceRole.VIEWER)
    conversation = _asked(
        acme,
        message_repository,
        conversation_repository,
        db_session,
    )

    # Nothing in the knowledge base, so the assistant hands over rather
    # than answering from what it happens to know -- which is the plan's
    # rule and the most common way a handoff actually happens.
    response = acme.client.post(
        acme.path("conversations", conversation, "ai-reply"),
        headers=acme.owner_headers,
    )
    assert response.json()["decision"] == "handoff"

    assert _unread(acme.client, agent) == 1
    assert _unread(acme.client, acme.owner_headers) == 1
    # A viewer reads a dashboard; fetching a customer is not their job.
    assert _unread(acme.client, viewer) == 0


def test_a_failed_delivery_tells_the_administrators(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    whatsapp_account_repository: WhatsAppAccountRepository,
    db_session: Session,
) -> None:
    _connected(acme, whatsapp_account_repository, db_session)
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    conversation = _thread(acme)
    messaging_provider.fail_with = "the provider said no"

    acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "hello"},
        headers=acme.owner_headers,
    )

    assert _unread(acme.client, acme.owner_headers) == 1
    # An agent cannot fix an integration, and being told about one they
    # cannot act on is the definition of noise.
    assert _unread(acme.client, agent) == 0


def test_one_outage_is_one_alert_however_many_messages_fail(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    whatsapp_account_repository: WhatsAppAccountRepository,
    db_session: Session,
) -> None:
    # A provider outage produces one failure per message, and one
    # notification per failure would bury the problem under itself.
    _connected(acme, whatsapp_account_repository, db_session)
    conversation = _thread(acme)
    messaging_provider.fail_with = "the provider said no"

    for _ in range(5):
        acme.client.post(
            acme.path("conversations", conversation, "messages"),
            json={"text": "hello"},
            headers=acme.owner_headers,
        )

    assert _unread(acme.client, acme.owner_headers) == 1


def test_a_second_outage_after_the_first_was_read_is_told_again(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    whatsapp_account_repository: WhatsAppAccountRepository,
    db_session: Session,
) -> None:
    # The rule is "not twice while it is still unread", not "once ever".
    _connected(acme, whatsapp_account_repository, db_session)
    conversation = _thread(acme)
    messaging_provider.fail_with = "the provider said no"
    acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "hello"},
        headers=acme.owner_headers,
    )
    acme.client.post(f"{FEED}/read-all", headers=acme.owner_headers)

    acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "hello again"},
        headers=acme.owner_headers,
    )

    assert _unread(acme.client, acme.owner_headers) == 1


def test_a_failed_delivery_still_fails(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    whatsapp_account_repository: WhatsAppAccountRepository,
    db_session: Session,
) -> None:
    # Notifying must not swallow the error the agent needs to see.
    _connected(acme, whatsapp_account_repository, db_session)
    conversation = _thread(acme)
    messaging_provider.fail_with = "the provider said no"

    response = acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "hello"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 502


def test_a_failed_ingestion_tells_the_administrators(
    acme: Tenant,
    embedding_provider: FakeEmbeddingProvider,
) -> None:
    source = acme.client.post(
        acme.path("knowledge", "sources"),
        json={"name": "Policies"},
        headers=acme.owner_headers,
    ).json()
    embedding_provider.fail_with = "the embedding provider said no"

    response = acme.client.post(
        acme.path("knowledge", "documents"),
        json={
            "knowledge_source_id": source["id"],
            "title": "Returns",
            "content": "Returns are accepted within 14 days of delivery.",
        },
        headers=acme.owner_headers,
    )

    assert response.status_code == 502
    feed = _feed(acme.client, acme.owner_headers)
    assert feed["items"][0]["kind"] == "knowledge_ingestion_failed"
    assert feed["items"][0]["metadata"]["title"] == "Returns"


# --- reading the feed -----------------------------------------------------


def test_the_feed_is_newest_first(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    agent_id = _user_id(user_repository, "agent@example.com")
    first = _thread(acme)
    second = _thread(acme)
    _assign(acme, first, agent_id)
    _assign(acme, second, agent_id)

    feed = _feed(acme.client, agent)

    assert feed["items"][0]["metadata"]["conversation_id"] == second


def test_the_feed_is_paged(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    agent_id = _user_id(user_repository, "agent@example.com")

    for _ in range(3):
        _assign(acme, _thread(acme), agent_id)

    page = _feed(acme.client, agent, page=2, page_size=2)

    assert page["total"] == 3
    assert len(page["items"]) == 1


def test_the_feed_can_be_narrowed_to_unread(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    agent_id = _user_id(user_repository, "agent@example.com")
    _assign(acme, _thread(acme), agent_id)
    _assign(acme, _thread(acme), agent_id)
    unread = _feed(acme.client, agent)["items"][0]["id"]

    acme.client.patch(f"{FEED}/{unread}/read", headers=agent)

    assert _feed(acme.client, agent, unread_only=True)["total"] == 1
    assert _feed(acme.client, agent)["total"] == 2


def test_a_feed_holds_every_business_somebody_works_in(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    # The reason these endpoints have no workspace in their path.
    acme = Tenant(client, user_repository, membership_repository, "acme-fashion")
    rival = Tenant(client, user_repository, membership_repository, "rival-store")
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    rival.member("agent@example.com", WorkspaceRole.AGENT)
    agent_id = _user_id(user_repository, "agent@example.com")

    _assign(acme, _thread(acme), agent_id)
    _assign(rival, _thread(rival), agent_id)

    feed = _feed(client, agent)
    assert feed["total"] == 2
    assert {item["workspace_id"] for item in feed["items"]} == {
        acme.workspace_id,
        rival.workspace_id,
    }


def test_a_feed_can_be_narrowed_to_one_business(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    acme = Tenant(client, user_repository, membership_repository, "acme-fashion")
    rival = Tenant(client, user_repository, membership_repository, "rival-store")
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    rival.member("agent@example.com", WorkspaceRole.AGENT)
    agent_id = _user_id(user_repository, "agent@example.com")
    _assign(acme, _thread(acme), agent_id)
    _assign(rival, _thread(rival), agent_id)

    feed = _feed(client, agent, workspace_id=acme.workspace_id)

    assert feed["total"] == 1
    assert _unread(client, agent, workspace_id=acme.workspace_id) == 1


def test_somebody_removed_from_a_business_stops_seeing_it(
    acme: Tenant,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> None:
    # A notification outlives the membership that justified it, and a
    # feed of a business somebody has left is a feed of its activity.
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    agent_id = _user_id(user_repository, "agent@example.com")
    _assign(acme, _thread(acme), agent_id)
    assert _unread(acme.client, agent) == 1

    membership = membership_repository.get_for_user(
        uuid.UUID(acme.workspace_id),
        agent_id,
    )
    assert membership is not None
    membership_repository.set_status(membership, MembershipStatus.REMOVED)
    db_session.flush()

    assert _feed(acme.client, agent)["total"] == 0
    assert _unread(acme.client, agent) == 0


def test_one_person_never_sees_anothers_notifications(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    other = acme.member("other@example.com", WorkspaceRole.AGENT)
    _assign(acme, _thread(acme), _user_id(user_repository, "agent@example.com"))

    assert _feed(acme.client, agent)["total"] == 1
    assert _feed(acme.client, other)["total"] == 0


# --- marking read ---------------------------------------------------------


def test_marking_one_read(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    _assign(acme, _thread(acme), _user_id(user_repository, "agent@example.com"))
    notification = _feed(acme.client, agent)["items"][0]

    response = acme.client.patch(
        f"{FEED}/{notification['id']}/read",
        headers=agent,
    )

    assert response.status_code == 200
    assert response.json()["read_at"] is not None
    assert _unread(acme.client, agent) == 0


def test_marking_read_twice_does_not_move_the_timestamp(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    # "When did they see this" stops being true the moment somebody
    # clicks twice.
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    _assign(acme, _thread(acme), _user_id(user_repository, "agent@example.com"))
    notification = _feed(acme.client, agent)["items"][0]["id"]

    first = acme.client.patch(f"{FEED}/{notification}/read", headers=agent).json()
    second = acme.client.patch(f"{FEED}/{notification}/read", headers=agent).json()

    # Compared as instants rather than as strings: the first response
    # serialises the value still in memory and the second the one read
    # back from PostgreSQL, so the same moment arrives under two offsets.
    assert datetime.fromisoformat(first["read_at"]) == datetime.fromisoformat(
        second["read_at"]
    )


def test_marking_somebody_elses_read_is_a_404(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    other = acme.member("other@example.com", WorkspaceRole.AGENT)
    _assign(acme, _thread(acme), _user_id(user_repository, "agent@example.com"))
    notification = _feed(acme.client, agent)["items"][0]["id"]

    response = acme.client.patch(f"{FEED}/{notification}/read", headers=other)

    assert response.status_code == 404
    assert _unread(acme.client, agent) == 1


def test_marking_all_read_says_how_many(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    agent_id = _user_id(user_repository, "agent@example.com")

    for _ in range(3):
        _assign(acme, _thread(acme), agent_id)

    response = acme.client.post(f"{FEED}/read-all", headers=agent)

    assert response.json() == {"marked_read": 3}
    assert _unread(acme.client, agent) == 0


def test_marking_all_read_again_clears_nothing(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    _assign(acme, _thread(acme), _user_id(user_repository, "agent@example.com"))
    acme.client.post(f"{FEED}/read-all", headers=agent)

    assert acme.client.post(f"{FEED}/read-all", headers=agent).json() == {
        "marked_read": 0
    }


def test_marking_all_read_can_be_narrowed_to_one_business(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    acme = Tenant(client, user_repository, membership_repository, "acme-fashion")
    rival = Tenant(client, user_repository, membership_repository, "rival-store")
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    rival.member("agent@example.com", WorkspaceRole.AGENT)
    agent_id = _user_id(user_repository, "agent@example.com")
    _assign(acme, _thread(acme), agent_id)
    _assign(rival, _thread(rival), agent_id)

    client.post(
        f"{FEED}/read-all",
        params={"workspace_id": acme.workspace_id},
        headers=agent,
    )

    assert _unread(client, agent) == 1


def test_marking_all_read_leaves_other_people_alone(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    other = acme.member("other@example.com", WorkspaceRole.AGENT)
    _assign(acme, _thread(acme), _user_id(user_repository, "agent@example.com"))
    _assign(acme, _thread(acme), _user_id(user_repository, "other@example.com"))

    acme.client.post(f"{FEED}/read-all", headers=agent)

    assert _unread(acme.client, other) == 1


# --- authentication -------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", FEED),
        ("get", f"{FEED}/unread-count"),
        ("post", f"{FEED}/read-all"),
        ("patch", f"{FEED}/3f2b0a6e-9c1d-4f8a-8f3e-2b6d5c4a1e70/read"),
    ],
)
def test_every_endpoint_requires_a_token(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    assert getattr(client, method)(path).status_code == 401


def test_the_ai_mode_a_thread_was_in_is_untouched(acme: Tenant) -> None:
    # A guard against the notification wiring changing what a handoff
    # does: the assistant's mode is the workspace's decision, and one
    # question it could not answer is not grounds for rewriting it.
    conversation = _thread(acme)

    detail = acme.client.get(
        acme.path("conversations", conversation),
        headers=acme.owner_headers,
    ).json()

    assert detail["ai_mode"] == AiMode.SUGGEST_ONLY.value
