"""Phase 6 acceptance: the conversation lifecycle."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ContactNotFoundError,
    ConversationAlreadyOpenError,
    ConversationNotFoundError,
    MembershipNotFoundError,
)
from app.models.conversation import AiMode, Conversation, ConversationStatus
from app.models.user import User
from app.models.workspace_membership import MembershipStatus, WorkspaceRole
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_event_repository import (
    ConversationEventRepository,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.contact import ContactCreate
from app.schemas.conversation import ConversationCreate, ConversationUpdate
from app.schemas.workspace import WorkspaceCreate
from app.services.contact_service import ContactService
from app.services.conversation_service import ConversationService
from app.services.workspace_service import WorkspaceAccess, WorkspaceService
from tests.support.services import notification_service

NUMBER = "+923001234567"
OTHER_NUMBER = "+923009876543"


def open_thread(
    service: ConversationService,
    access: WorkspaceAccess,
    contact_id: uuid.UUID,
) -> Conversation:
    """Open a thread and hand back the conversation itself.

    The service answers every call with an inbox row -- the conversation
    together with the contact, the assignee and the last message -- because
    that is what the API renders. These tests are about the lifecycle, so
    they unwrap it here rather than saying `.conversation` on every line.
    """
    return service.create(
        access, ConversationCreate(contact_id=contact_id)
    ).conversation


@pytest.fixture
def workspaces(
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> WorkspaceService:
    return WorkspaceService(
        session=db_session,
        workspaces=workspace_repository,
        memberships=membership_repository,
    )


@pytest.fixture
def contacts(
    db_session: Session,
    contact_repository: ContactRepository,
) -> ContactService:
    return ContactService(session=db_session, contacts=contact_repository)


@pytest.fixture
def service(
    db_session: Session,
    conversation_repository: ConversationRepository,
    contact_repository: ContactRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> ConversationService:
    return ConversationService(
        session=db_session,
        conversations=conversation_repository,
        contacts=contact_repository,
        memberships=membership_repository,
        events=ConversationEventRepository(db_session),
        notifications=notification_service(db_session),
    )


class Business:
    def __init__(
        self,
        session: Session,
        workspaces: WorkspaceService,
        memberships: WorkspaceMembershipRepository,
        contacts: ContactService,
        slug: str,
    ) -> None:
        self._session = session
        self._memberships = memberships
        self._contacts = contacts
        self._people = 0

        self.owner = self.user(f"owner-{slug}@example.com")
        self.workspace = workspaces.create(
            WorkspaceCreate(name=slug.title(), slug=slug),
            creator=self.owner,
        )
        self.access = workspaces.access(self.workspace.id, self.owner)

    def user(self, email: str) -> User:
        self._people += 1
        user = User(name="Someone", email=email, hashed_password="not a real hash")
        self._session.add(user)
        self._session.flush()

        return user

    def member(self, email: str, role: WorkspaceRole = WorkspaceRole.AGENT) -> User:
        user = self.user(email)
        self._memberships.create(
            workspace_id=self.workspace.id,
            user_id=user.id,
            role=role,
        )

        return user

    def contact(self, number: str = NUMBER):
        return self._contacts.create(self.access, ContactCreate(phone_number=number))


@pytest.fixture
def acme(
    db_session: Session,
    workspaces: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
    contacts: ContactService,
) -> Business:
    return Business(
        db_session, workspaces, membership_repository, contacts, "acme-fashion"
    )


@pytest.fixture
def rival(
    db_session: Session,
    workspaces: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
    contacts: ContactService,
) -> Business:
    return Business(
        db_session, workspaces, membership_repository, contacts, "rival-store"
    )


# --- opening ----------------------------------------------------------------


def test_a_conversation_opens_against_a_contact(
    service: ConversationService,
    acme: Business,
) -> None:
    contact = acme.contact()

    conversation = open_thread(service, acme.access, contact.id)

    assert conversation.contact_id == contact.id
    assert conversation.workspace_id == acme.workspace.id
    assert conversation.status == ConversationStatus.OPEN
    assert conversation.ai_mode == AiMode.SUGGEST_ONLY


def test_a_contact_cannot_have_two_live_conversations(
    service: ConversationService,
    acme: Business,
) -> None:
    contact = acme.contact()
    open_thread(service, acme.access, contact.id)

    with pytest.raises(ConversationAlreadyOpenError):
        open_thread(service, acme.access, contact.id)


def test_a_contact_from_another_business_cannot_be_used(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    # The answer is "no such contact", not a foreign key violation.
    theirs = rival.contact()

    with pytest.raises(ContactNotFoundError):
        open_thread(service, acme.access, theirs.id)


def test_a_contact_that_does_not_exist_is_refused(
    service: ConversationService,
    acme: Business,
) -> None:
    with pytest.raises(ContactNotFoundError):
        open_thread(service, acme.access, uuid.uuid4())


# --- reading ----------------------------------------------------------------


def test_another_business_cannot_read_your_conversation(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)

    with pytest.raises(ConversationNotFoundError):
        service.get(rival.access, conversation.id)


def test_listing_never_crosses_into_another_business(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    mine = open_thread(service, acme.access, acme.contact().id)
    open_thread(service, rival.access, rival.contact().id)

    rows, total = service.list_for(acme.access)

    assert [row.conversation.id for row in rows] == [mine.id]
    assert total == 1


def test_conversations_can_be_filtered_by_status(
    service: ConversationService,
    acme: Business,
) -> None:
    first = open_thread(service, acme.access, acme.contact(NUMBER).id)
    open_thread(service, acme.access, acme.contact(OTHER_NUMBER).id)
    service.close(acme.access, first.id)

    closed, total = service.list_for(
        acme.access,
        statuses=[ConversationStatus.CLOSED],
    )

    assert total == 1
    assert closed[0].conversation.id == first.id


def test_conversations_can_be_filtered_by_assignee(
    service: ConversationService,
    acme: Business,
) -> None:
    agent = acme.member("agent@example.com")
    mine = open_thread(service, acme.access, acme.contact(NUMBER).id)
    open_thread(service, acme.access, acme.contact(OTHER_NUMBER).id)
    service.assign(acme.access, mine.id, agent.id)

    assigned, total = service.list_for(acme.access, assigned_user_id=agent.id)
    unassigned, unassigned_total = service.list_for(acme.access, unassigned=True)

    assert total == 1
    assert assigned[0].conversation.id == mine.id
    assert unassigned_total == 1
    assert unassigned[0].conversation.id != mine.id


# --- assignment -------------------------------------------------------------


def test_a_conversation_can_be_assigned_and_unassigned(
    service: ConversationService,
    acme: Business,
) -> None:
    agent = acme.member("agent@example.com")
    conversation = open_thread(service, acme.access, acme.contact().id)

    assigned = service.assign(acme.access, conversation.id, agent.id)
    assert assigned.conversation.assigned_user_id == agent.id
    # The row carries the person, not only their id: an inbox that has to
    # look up a name to say who has a thread is an inbox making a second
    # request per row.
    assert assigned.assignee is not None
    assert assigned.assignee.email == "agent@example.com"

    cleared = service.assign(acme.access, conversation.id, None)
    assert cleared.conversation.assigned_user_id is None
    assert cleared.assignee is None


def test_a_conversation_cannot_be_assigned_outside_the_workspace(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    # It would put a customer's history on a screen that should not have
    # it, through a field that looks like bookkeeping.
    conversation = open_thread(service, acme.access, acme.contact().id)

    with pytest.raises(MembershipNotFoundError):
        service.assign(acme.access, conversation.id, rival.owner.id)


def test_a_removed_member_cannot_be_assigned(
    service: ConversationService,
    acme: Business,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    agent = acme.member("agent@example.com")
    membership = membership_repository.get_for_user(acme.workspace.id, agent.id)
    assert membership is not None
    membership_repository.set_status(membership, MembershipStatus.REMOVED)

    conversation = open_thread(service, acme.access, acme.contact().id)

    with pytest.raises(MembershipNotFoundError):
        service.assign(acme.access, conversation.id, agent.id)


# --- closing and reopening --------------------------------------------------


def test_closing_stamps_the_time_it_closed(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)

    closed = service.close(acme.access, conversation.id).conversation

    assert closed.status == ConversationStatus.CLOSED
    assert closed.closed_at is not None


def test_closing_twice_is_not_an_error(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)
    first = service.close(acme.access, conversation.id).conversation.closed_at

    assert service.close(acme.access, conversation.id).conversation.closed_at == first


def test_reopening_clears_the_closing_time_and_restarts_the_clock(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)
    opened_first = conversation.opened_at
    service.close(acme.access, conversation.id)

    reopened = service.reopen(acme.access, conversation.id).conversation

    assert reopened.status == ConversationStatus.OPEN
    assert reopened.closed_at is None
    assert reopened.opened_at >= opened_first


def test_reopening_is_refused_if_a_newer_thread_took_its_place(
    service: ConversationService,
    acme: Business,
) -> None:
    contact = acme.contact()
    first = open_thread(service, acme.access, contact.id)
    service.close(acme.access, first.id)
    open_thread(service, acme.access, contact.id)

    with pytest.raises(ConversationAlreadyOpenError):
        service.reopen(acme.access, first.id)


def test_reopening_an_open_conversation_changes_nothing(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)
    opened = conversation.opened_at

    assert service.reopen(acme.access, conversation.id).conversation.opened_at == opened


# --- updating ---------------------------------------------------------------


def test_the_ai_mode_can_be_changed(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(ai_mode=AiMode.DISABLED),
    ).conversation

    assert updated.ai_mode == AiMode.DISABLED


def test_a_conversation_can_be_marked_pending(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(status=ConversationStatus.PENDING),
    ).conversation

    assert updated.status == ConversationStatus.PENDING
    assert updated.closed_at is None


def test_closing_through_the_update_stamps_the_time_too(
    service: ConversationService,
    acme: Business,
) -> None:
    # Two ways to say a thing is fine; two implementations of it are what
    # let the timestamps drift apart.
    conversation = open_thread(service, acme.access, acme.contact().id)

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(status=ConversationStatus.CLOSED),
    ).conversation

    assert updated.status == ConversationStatus.CLOSED
    assert updated.closed_at is not None


def test_reopening_through_the_update_clears_it(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)
    service.close(acme.access, conversation.id)

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(status=ConversationStatus.OPEN),
    ).conversation

    assert updated.closed_at is None


def test_an_empty_update_changes_nothing(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(),
    ).conversation

    assert updated.status == ConversationStatus.OPEN
    assert updated.ai_mode == AiMode.SUGGEST_ONLY


# --- the inbox row ----------------------------------------------------------


def test_the_service_answers_with_the_row_an_inbox_renders(
    service: ConversationService,
    acme: Business,
) -> None:
    agent = acme.member("agent@example.com")
    contact = acme.contact()
    conversation = open_thread(service, acme.access, contact.id)
    service.assign(acme.access, conversation.id, agent.id)

    row = service.detail(acme.access, conversation.id)

    assert row.contact.id == contact.id
    assert row.assignee is not None
    assert row.assignee.id == agent.id
    assert row.last_message is None


def test_another_business_cannot_read_the_row_either(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)

    with pytest.raises(ConversationNotFoundError):
        service.detail(rival.access, conversation.id)


def test_the_inbox_can_be_searched_by_who_the_thread_is_with(
    service: ConversationService,
    acme: Business,
    contacts: ContactService,
) -> None:
    ayesha = contacts.create(
        acme.access,
        ContactCreate(phone_number=NUMBER, name="Ayesha Khan"),
    )
    bilal = contacts.create(
        acme.access,
        ContactCreate(phone_number=OTHER_NUMBER, name="Bilal Raza"),
    )
    wanted = open_thread(service, acme.access, ayesha.id)
    open_thread(service, acme.access, bilal.id)

    rows, total = service.list_for(acme.access, search="ayesha")

    assert total == 1
    assert rows[0].conversation.id == wanted.id


def test_marking_read_clears_the_count(
    service: ConversationService,
    acme: Business,
    conversation_repository: ConversationRepository,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)
    conversation_repository.record_activity(
        conversation,
        datetime(2026, 6, 1, tzinfo=UTC),
        unread=True,
    )

    row = service.mark_read(acme.access, conversation.id)

    assert row.conversation.unread_count == 0
    assert row.conversation.last_read_at is not None


def test_marking_a_thread_read_that_nobody_wrote_to_is_not_an_error(
    service: ConversationService,
    acme: Business,
) -> None:
    # So a client can call it whenever a thread is opened.
    conversation = open_thread(service, acme.access, acme.contact().id)

    assert (
        service.mark_read(acme.access, conversation.id).conversation.unread_count == 0
    )


def test_another_business_cannot_mark_your_thread_read(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    conversation = open_thread(service, acme.access, acme.contact().id)

    with pytest.raises(ConversationNotFoundError):
        service.mark_read(rival.access, conversation.id)
