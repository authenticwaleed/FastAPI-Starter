"""Phase 6 acceptance: what the database refuses, whatever the code does."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.conversation import Channel, Conversation, ConversationStatus
from app.models.message import (
    Direction,
    Message,
    MessageStatus,
    SenderType,
)
from app.models.user import User
from app.models.workspace import Workspace


def _workspace(session: Session, slug: str) -> Workspace:
    user = User(
        name="Someone",
        email=f"owner-{slug}@example.com",
        hashed_password="not a real hash",
    )
    session.add(user)
    session.flush()

    workspace = Workspace(name=slug.title(), slug=slug, created_by_user_id=user.id)
    session.add(workspace)
    session.flush()

    return workspace


def _contact(session: Session, workspace: Workspace, number: str) -> Contact:
    contact = Contact(workspace_id=workspace.id, phone_number=number)
    session.add(contact)
    session.flush()

    return contact


def _conversation(session: Session, workspace: Workspace, contact: Contact):
    conversation = Conversation(workspace_id=workspace.id, contact_id=contact.id)
    session.add(conversation)
    session.flush()

    return conversation


def _message(session: Session, conversation: Conversation, text: str) -> Message:
    message = Message(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        sender_type=SenderType.AGENT,
        direction=Direction.OUTBOUND,
        status=MessageStatus.QUEUED,
        text_body=text,
    )
    session.add(message)
    session.flush()

    return message


@pytest.fixture
def acme(db_session: Session) -> Workspace:
    return _workspace(db_session, "acme-fashion")


@pytest.fixture
def rival(db_session: Session) -> Workspace:
    return _workspace(db_session, "rival-store")


def test_a_contact_cannot_hold_two_live_conversations(
    db_session: Session,
    acme: Workspace,
) -> None:
    # Two would split a customer's history down the middle, with half of
    # it in an inbox row nobody is looking at.
    contact = _contact(db_session, acme, "+923001234567")
    _conversation(db_session, acme, contact)

    with pytest.raises(IntegrityError):
        _conversation(db_session, acme, contact)


def test_a_closed_conversation_leaves_room_for_the_next(
    db_session: Session,
    acme: Workspace,
) -> None:
    # The index is partial, so history accumulates without blocking.
    contact = _contact(db_session, acme, "+923001234567")
    first = _conversation(db_session, acme, contact)

    first.status = ConversationStatus.CLOSED
    db_session.flush()

    assert _conversation(db_session, acme, contact).id != first.id


def test_many_conversations_may_be_closed_for_one_contact(
    db_session: Session,
    acme: Workspace,
) -> None:
    contact = _contact(db_session, acme, "+923001234567")

    for _ in range(3):
        conversation = _conversation(db_session, acme, contact)
        conversation.status = ConversationStatus.CLOSED
        db_session.flush()


def test_a_conversation_cannot_name_another_workspaces_contact(
    db_session: Session,
    acme: Workspace,
    rival: Workspace,
) -> None:
    # The composite foreign key, doing the job the application would
    # otherwise have to remember to do on every write.
    theirs = _contact(db_session, acme, "+923001234567")

    with pytest.raises(IntegrityError):
        _conversation(db_session, rival, theirs)


def test_a_message_cannot_name_another_workspaces_conversation(
    db_session: Session,
    acme: Workspace,
    rival: Workspace,
) -> None:
    contact = _contact(db_session, acme, "+923001234567")
    conversation = _conversation(db_session, acme, contact)

    stray = Message(
        workspace_id=rival.id,
        conversation_id=conversation.id,
        sender_type=SenderType.AGENT,
        direction=Direction.OUTBOUND,
        status=MessageStatus.QUEUED,
        text_body="wrong workspace",
    )
    db_session.add(stray)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_messages_get_a_strictly_increasing_sequence(
    db_session: Session,
    acme: Workspace,
) -> None:
    # Written in one transaction, so all three share a created_at. The
    # sequence is what keeps the thread in the order it was said.
    contact = _contact(db_session, acme, "+923001234567")
    conversation = _conversation(db_session, acme, contact)

    written = [_message(db_session, conversation, f"line {i}") for i in range(3)]

    sequences = [message.sequence for message in written]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == 3
    assert len({message.created_at for message in written}) == 1


def test_an_external_message_id_is_unique_within_a_workspace(
    db_session: Session,
    acme: Workspace,
) -> None:
    # What will make a retried webhook idempotent.
    contact = _contact(db_session, acme, "+923001234567")
    conversation = _conversation(db_session, acme, contact)

    first = _message(db_session, conversation, "one")
    first.external_message_id = "wamid.ABC"
    db_session.flush()

    second = _message(db_session, conversation, "two")
    second.external_message_id = "wamid.ABC"

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_workspaces_may_see_the_same_provider_id(
    db_session: Session,
    acme: Workspace,
    rival: Workspace,
) -> None:
    # Two businesses' providers know nothing of each other.
    for workspace in (acme, rival):
        contact = _contact(db_session, workspace, "+923001234567")
        conversation = _conversation(db_session, workspace, contact)
        message = _message(db_session, conversation, "hello")
        message.external_message_id = "wamid.ABC"
        db_session.flush()


def test_closing_a_workspace_contact_takes_its_conversations(
    db_session: Session,
    acme: Workspace,
) -> None:
    contact = _contact(db_session, acme, "+923001234567")
    conversation = _conversation(db_session, acme, contact)
    _message(db_session, conversation, "hello")
    conversation_id = conversation.id

    db_session.delete(contact)
    db_session.flush()
    db_session.expunge_all()

    assert db_session.get(Conversation, conversation_id) is None


def test_a_new_conversation_is_open_and_unassigned(
    db_session: Session,
    acme: Workspace,
) -> None:
    contact = _contact(db_session, acme, "+923001234567")
    conversation = _conversation(db_session, acme, contact)
    db_session.refresh(conversation)

    assert conversation.status == ConversationStatus.OPEN
    assert conversation.assigned_user_id is None
    assert conversation.last_message_at is None
    assert conversation.closed_at is None
    assert conversation.channel == Channel.WHATSAPP


def test_the_database_refuses_an_invented_sender_type(
    db_session: Session,
    acme: Workspace,
) -> None:
    contact = _contact(db_session, acme, "+923001234567")
    conversation = _conversation(db_session, acme, contact)

    db_session.add(
        Message(
            workspace_id=acme.id,
            conversation_id=conversation.id,
            sender_type="robot",  # type: ignore[arg-type]
            direction=Direction.OUTBOUND,
            status=MessageStatus.QUEUED,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_conversation_id_from_nowhere_is_refused(
    db_session: Session,
    acme: Workspace,
) -> None:
    db_session.add(
        Message(
            workspace_id=acme.id,
            conversation_id=uuid.uuid4(),
            sender_type=SenderType.AGENT,
            direction=Direction.OUTBOUND,
            status=MessageStatus.QUEUED,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
