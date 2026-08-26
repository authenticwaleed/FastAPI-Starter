"""Phase 6 acceptance: the conversation lifecycle."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ContactNotFoundError,
    ConversationAlreadyOpenError,
    ConversationNotFoundError,
    MembershipNotFoundError,
)
from app.models.conversation import AiMode, ConversationStatus
from app.models.user import User
from app.models.workspace_membership import MembershipStatus, WorkspaceRole
from app.repositories.contact_repository import ContactRepository
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
from app.services.workspace_service import WorkspaceService

NUMBER = "+923001234567"
OTHER_NUMBER = "+923009876543"


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

    conversation = service.create(
        acme.access, ConversationCreate(contact_id=contact.id)
    )

    assert conversation.contact_id == contact.id
    assert conversation.workspace_id == acme.workspace.id
    assert conversation.status == ConversationStatus.OPEN
    assert conversation.ai_mode == AiMode.SUGGEST_ONLY


def test_a_contact_cannot_have_two_live_conversations(
    service: ConversationService,
    acme: Business,
) -> None:
    contact = acme.contact()
    service.create(acme.access, ConversationCreate(contact_id=contact.id))

    with pytest.raises(ConversationAlreadyOpenError):
        service.create(acme.access, ConversationCreate(contact_id=contact.id))


def test_a_contact_from_another_business_cannot_be_used(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    # The answer is "no such contact", not a foreign key violation.
    theirs = rival.contact()

    with pytest.raises(ContactNotFoundError):
        service.create(acme.access, ConversationCreate(contact_id=theirs.id))


def test_a_contact_that_does_not_exist_is_refused(
    service: ConversationService,
    acme: Business,
) -> None:
    with pytest.raises(ContactNotFoundError):
        service.create(acme.access, ConversationCreate(contact_id=uuid.uuid4()))


# --- reading ----------------------------------------------------------------


def test_another_business_cannot_read_your_conversation(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

    with pytest.raises(ConversationNotFoundError):
        service.get(rival.access, conversation.id)


def test_listing_never_crosses_into_another_business(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    mine = service.create(acme.access, ConversationCreate(contact_id=acme.contact().id))
    service.create(rival.access, ConversationCreate(contact_id=rival.contact().id))

    conversations, total = service.list_for(acme.access)

    assert [c.id for c in conversations] == [mine.id]
    assert total == 1


def test_conversations_can_be_filtered_by_status(
    service: ConversationService,
    acme: Business,
) -> None:
    first = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact(NUMBER).id)
    )
    service.create(
        acme.access, ConversationCreate(contact_id=acme.contact(OTHER_NUMBER).id)
    )
    service.close(acme.access, first.id)

    closed, total = service.list_for(acme.access, status=ConversationStatus.CLOSED)

    assert total == 1
    assert closed[0].id == first.id


def test_conversations_can_be_filtered_by_assignee(
    service: ConversationService,
    acme: Business,
) -> None:
    agent = acme.member("agent@example.com")
    mine = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact(NUMBER).id)
    )
    service.create(
        acme.access, ConversationCreate(contact_id=acme.contact(OTHER_NUMBER).id)
    )
    service.assign(acme.access, mine.id, agent.id)

    assigned, total = service.list_for(acme.access, assigned_user_id=agent.id)
    unassigned, unassigned_total = service.list_for(acme.access, unassigned=True)

    assert total == 1
    assert assigned[0].id == mine.id
    assert unassigned_total == 1
    assert unassigned[0].id != mine.id


# --- assignment -------------------------------------------------------------


def test_a_conversation_can_be_assigned_and_unassigned(
    service: ConversationService,
    acme: Business,
) -> None:
    agent = acme.member("agent@example.com")
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

    assert service.assign(acme.access, conversation.id, agent.id).assigned_user_id == (
        agent.id
    )
    assert service.assign(acme.access, conversation.id, None).assigned_user_id is None


def test_a_conversation_cannot_be_assigned_outside_the_workspace(
    service: ConversationService,
    acme: Business,
    rival: Business,
) -> None:
    # It would put a customer's history on a screen that should not have
    # it, through a field that looks like bookkeeping.
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

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

    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

    with pytest.raises(MembershipNotFoundError):
        service.assign(acme.access, conversation.id, agent.id)


# --- closing and reopening --------------------------------------------------


def test_closing_stamps_the_time_it_closed(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

    closed = service.close(acme.access, conversation.id)

    assert closed.status == ConversationStatus.CLOSED
    assert closed.closed_at is not None


def test_closing_twice_is_not_an_error(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )
    first = service.close(acme.access, conversation.id).closed_at

    assert service.close(acme.access, conversation.id).closed_at == first


def test_reopening_clears_the_closing_time_and_restarts_the_clock(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )
    opened_first = conversation.opened_at
    service.close(acme.access, conversation.id)

    reopened = service.reopen(acme.access, conversation.id)

    assert reopened.status == ConversationStatus.OPEN
    assert reopened.closed_at is None
    assert reopened.opened_at >= opened_first


def test_reopening_is_refused_if_a_newer_thread_took_its_place(
    service: ConversationService,
    acme: Business,
) -> None:
    contact = acme.contact()
    first = service.create(acme.access, ConversationCreate(contact_id=contact.id))
    service.close(acme.access, first.id)
    service.create(acme.access, ConversationCreate(contact_id=contact.id))

    with pytest.raises(ConversationAlreadyOpenError):
        service.reopen(acme.access, first.id)


def test_reopening_an_open_conversation_changes_nothing(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )
    opened = conversation.opened_at

    assert service.reopen(acme.access, conversation.id).opened_at == opened


# --- updating ---------------------------------------------------------------


def test_the_ai_mode_can_be_changed(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(ai_mode=AiMode.DISABLED),
    )

    assert updated.ai_mode == AiMode.DISABLED


def test_a_conversation_can_be_marked_pending(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(status=ConversationStatus.PENDING),
    )

    assert updated.status == ConversationStatus.PENDING
    assert updated.closed_at is None


def test_closing_through_the_update_stamps_the_time_too(
    service: ConversationService,
    acme: Business,
) -> None:
    # Two ways to say a thing is fine; two implementations of it are what
    # let the timestamps drift apart.
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(status=ConversationStatus.CLOSED),
    )

    assert updated.status == ConversationStatus.CLOSED
    assert updated.closed_at is not None


def test_reopening_through_the_update_clears_it(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )
    service.close(acme.access, conversation.id)

    updated = service.update(
        acme.access,
        conversation.id,
        ConversationUpdate(status=ConversationStatus.OPEN),
    )

    assert updated.closed_at is None


def test_an_empty_update_changes_nothing(
    service: ConversationService,
    acme: Business,
) -> None:
    conversation = service.create(
        acme.access, ConversationCreate(contact_id=acme.contact().id)
    )

    updated = service.update(acme.access, conversation.id, ConversationUpdate())

    assert updated.status == ConversationStatus.OPEN
    assert updated.ai_mode == AiMode.SUGGEST_ONLY
