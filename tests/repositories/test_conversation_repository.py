"""Phase 8 acceptance: the query behind an inbox row, and the unread count.

The API tests prove what a row contains. These prove how it is fetched and
how the count moves, which is where the two things that could quietly go
wrong live: a join that stops being one query, and a counter that loses an
increment when two of a customer's messages land at once.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.contact import Contact, ContactStatus
from app.models.conversation import Channel, Conversation, ConversationStatus
from app.models.message import Direction, MessageStatus, SenderType
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import (
    PREVIEW_LENGTH,
    ConversationRepository,
)
from app.repositories.message_repository import MessageRepository

NUMBER = "+923001234567"
OTHER_NUMBER = "+923009876543"


def _user(session: Session, email: str, name: str = "Someone") -> User:
    user = User(name=name, email=email, hashed_password="not a real hash")
    session.add(user)
    session.flush()

    return user


@pytest.fixture
def acme(db_session: Session) -> Workspace:
    return _workspace(db_session, "acme-fashion")


@pytest.fixture
def rival(db_session: Session) -> Workspace:
    return _workspace(db_session, "rival-store")


def _workspace(session: Session, slug: str) -> Workspace:
    owner = _user(session, f"owner-{slug}@example.com")
    workspace = Workspace(name=slug.title(), slug=slug, created_by_user_id=owner.id)
    session.add(workspace)
    session.flush()

    return workspace


@pytest.fixture
def contact(
    contact_repository: ContactRepository,
    acme: Workspace,
) -> Contact:
    return contact_repository.create(
        workspace_id=acme.id,
        phone_number=NUMBER,
        name="Ayesha",
        email=None,
        status=ContactStatus.LEAD,
        source="whatsapp",
        external_id=None,
        meta={},
    )


@pytest.fixture
def conversation(
    conversation_repository: ConversationRepository,
    acme: Workspace,
    contact: Contact,
) -> Conversation:
    return conversation_repository.create(
        workspace_id=acme.id,
        contact_id=contact.id,
        channel=Channel.WHATSAPP,
    )


def _say(
    messages: MessageRepository,
    conversation: Conversation,
    text: str,
    *,
    sender_type: SenderType = SenderType.CUSTOMER,
) -> None:
    inbound = sender_type == SenderType.CUSTOMER
    messages.create(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        sender_type=sender_type,
        direction=Direction.INBOUND if inbound else Direction.OUTBOUND,
        channel=Channel.WHATSAPP,
        status=MessageStatus.RECEIVED if inbound else MessageStatus.SENT,
        text=text,
    )


# --- the enriched row -------------------------------------------------------


def test_a_row_carries_the_contact_the_assignee_and_the_last_word(
    db_session: Session,
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
    acme: Workspace,
    contact: Contact,
    conversation: Conversation,
) -> None:
    agent = _user(db_session, "agent@example.com", "Ali")
    conversation_repository.set_assignee(conversation, agent.id)
    _say(message_repository, conversation, "first")
    _say(message_repository, conversation, "second", sender_type=SenderType.AGENT)

    row = conversation_repository.get_row(acme.id, conversation.id)

    assert row is not None
    assert row.contact.id == contact.id
    assert row.assignee is not None
    assert row.assignee.name == "Ali"
    assert row.last_message is not None
    assert row.last_message.text == "second"
    assert row.last_message.sender_type == SenderType.AGENT
    assert row.last_message.direction == Direction.OUTBOUND


def test_a_row_survives_having_no_assignee_and_nothing_said(
    conversation_repository: ConversationRepository,
    acme: Workspace,
    conversation: Conversation,
) -> None:
    # Both are the ordinary state of a shared inbox, not an edge case: an
    # unassigned thread is the default, and a thread opened from the
    # dashboard has nothing in it yet.
    row = conversation_repository.get_row(acme.id, conversation.id)

    assert row is not None
    assert row.assignee is None
    assert row.last_message is None


def test_the_preview_is_cut_in_the_database(
    conversation_repository: ConversationRepository,
    message_repository: MessageRepository,
    acme: Workspace,
    conversation: Conversation,
) -> None:
    _say(message_repository, conversation, "x" * 1000)

    row = conversation_repository.get_row(acme.id, conversation.id)

    assert row is not None
    assert row.last_message is not None
    assert row.last_message.text == "x" * PREVIEW_LENGTH


def test_a_row_is_not_readable_from_another_workspace(
    conversation_repository: ConversationRepository,
    rival: Workspace,
    conversation: Conversation,
) -> None:
    assert conversation_repository.get_row(rival.id, conversation.id) is None


def test_ordering_puts_the_most_recently_active_thread_first(
    conversation_repository: ConversationRepository,
    contact_repository: ContactRepository,
    acme: Workspace,
    conversation: Conversation,
) -> None:
    other_contact = contact_repository.create(
        workspace_id=acme.id,
        phone_number=OTHER_NUMBER,
        name=None,
        email=None,
        status=ContactStatus.LEAD,
        source=None,
        external_id=None,
        meta={},
    )
    other = conversation_repository.create(
        workspace_id=acme.id,
        contact_id=other_contact.id,
        channel=Channel.WHATSAPP,
    )
    conversation_repository.record_activity(other, datetime(2026, 1, 1, tzinfo=UTC))
    conversation_repository.record_activity(
        conversation, datetime(2026, 6, 1, tzinfo=UTC)
    )

    rows = conversation_repository.list_for_workspace(acme.id, limit=10, offset=0)

    assert [row.conversation.id for row in rows] == [conversation.id, other.id]


def test_a_thread_with_nothing_said_sorts_last_rather_than_vanishing(
    conversation_repository: ConversationRepository,
    contact_repository: ContactRepository,
    acme: Workspace,
    conversation: Conversation,
) -> None:
    silent_contact = contact_repository.create(
        workspace_id=acme.id,
        phone_number=OTHER_NUMBER,
        name=None,
        email=None,
        status=ContactStatus.LEAD,
        source=None,
        external_id=None,
        meta={},
    )
    silent = conversation_repository.create(
        workspace_id=acme.id,
        contact_id=silent_contact.id,
        channel=Channel.WHATSAPP,
    )
    conversation_repository.record_activity(
        conversation, datetime(2026, 6, 1, tzinfo=UTC)
    )

    rows = conversation_repository.list_for_workspace(acme.id, limit=10, offset=0)

    assert [row.conversation.id for row in rows] == [conversation.id, silent.id]


# --- filters ----------------------------------------------------------------


def test_several_statuses_can_be_asked_for_at_once(
    conversation_repository: ConversationRepository,
    acme: Workspace,
    conversation: Conversation,
) -> None:
    conversation_repository.set_status(conversation, ConversationStatus.PENDING)

    wanted = [ConversationStatus.OPEN, ConversationStatus.PENDING]
    rows = conversation_repository.list_for_workspace(
        acme.id, limit=10, offset=0, statuses=wanted
    )

    assert [row.conversation.id for row in rows] == [conversation.id]
    assert conversation_repository.count_for_workspace(acme.id, statuses=wanted) == 1
    assert (
        conversation_repository.count_for_workspace(
            acme.id, statuses=[ConversationStatus.CLOSED]
        )
        == 0
    )


def test_the_page_and_its_total_agree_about_a_search(
    conversation_repository: ConversationRepository,
    contact_repository: ContactRepository,
    acme: Workspace,
    conversation: Conversation,
) -> None:
    # A page and a total that disagree show up as a pagination control
    # promising a page which turns out to be empty.
    other = contact_repository.create(
        workspace_id=acme.id,
        phone_number=OTHER_NUMBER,
        name="Bilal",
        email=None,
        status=ContactStatus.LEAD,
        source=None,
        external_id=None,
        meta={},
    )
    conversation_repository.create(
        workspace_id=acme.id,
        contact_id=other.id,
        channel=Channel.WHATSAPP,
    )

    rows = conversation_repository.list_for_workspace(
        acme.id, limit=10, offset=0, search="ayesha"
    )

    assert [row.conversation.id for row in rows] == [conversation.id]
    assert conversation_repository.count_for_workspace(acme.id, search="ayesha") == 1


def test_unassigned_wins_over_an_assignee(
    db_session: Session,
    conversation_repository: ConversationRepository,
    acme: Workspace,
    conversation: Conversation,
) -> None:
    # Asking for both is a contradiction, and the one with no answer should
    # not silently become the one with an answer.
    agent = _user(db_session, "agent@example.com")
    conversation_repository.set_assignee(conversation, agent.id)

    rows = conversation_repository.list_for_workspace(
        acme.id,
        limit=10,
        offset=0,
        assigned_user_id=agent.id,
        unassigned=True,
    )

    assert rows == []


# --- unread -----------------------------------------------------------------


def test_a_customers_message_raises_the_unread_count(
    conversation_repository: ConversationRepository,
    conversation: Conversation,
) -> None:
    at = datetime(2026, 6, 1, tzinfo=UTC)

    conversation_repository.record_activity(conversation, at, unread=True)

    assert conversation.unread_count == 1
    assert conversation.last_message_at == at


def test_the_count_moves_by_an_expression_rather_than_a_number(
    db_session: Session,
    conversation_repository: ConversationRepository,
    conversation: Conversation,
) -> None:
    """Two of a customer's messages are two, not one.

    The increment is written as SQL rather than read into Python and
    written back, so the row is locked by the update. A read-then-write
    would let the second of two concurrent deliveries overwrite the first,
    and the badge would undercount exactly when an inbox is busiest.
    """
    at = datetime(2026, 6, 1, tzinfo=UTC)
    conversation_repository.record_activity(conversation, at, unread=True)
    conversation_repository.record_activity(conversation, at, unread=True)

    db_session.expire(conversation)

    assert conversation.unread_count == 2


def test_the_teams_own_activity_leaves_the_count_alone(
    conversation_repository: ConversationRepository,
    conversation: Conversation,
) -> None:
    at = datetime(2026, 6, 1, tzinfo=UTC)
    conversation_repository.record_activity(conversation, at, unread=True)

    conversation_repository.record_activity(conversation, at)

    assert conversation.unread_count == 1


def test_marking_read_clears_the_count_and_stamps_the_time(
    conversation_repository: ConversationRepository,
    conversation: Conversation,
) -> None:
    at = datetime(2026, 6, 1, tzinfo=UTC)
    conversation_repository.record_activity(conversation, at, unread=True)

    conversation_repository.mark_read(conversation, at)

    assert conversation.unread_count == 0
    assert conversation.last_read_at == at


def test_a_new_conversation_starts_with_nothing_unread(
    conversation_repository: ConversationRepository,
    acme: Workspace,
    conversation: Conversation,
) -> None:
    row = conversation_repository.get_row(acme.id, conversation.id)

    assert row is not None
    assert row.conversation.unread_count == 0
    assert row.conversation.last_read_at is None


def test_an_unknown_conversation_has_no_row(
    conversation_repository: ConversationRepository,
    acme: Workspace,
) -> None:
    assert conversation_repository.get_row(acme.id, uuid.uuid4()) is None
