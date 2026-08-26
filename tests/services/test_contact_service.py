"""Phase 5 acceptance: end customers, kept inside their own workspace."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ContactAlreadyExistsError,
    ContactNotFoundError,
)
from app.models.contact import ContactStatus
from app.models.user import User
from app.repositories.contact_repository import ContactRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.contact import ContactCreate, ContactUpdate
from app.schemas.workspace import WorkspaceCreate
from app.services.contact_service import ContactService
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
def service(
    db_session: Session,
    contact_repository: ContactRepository,
) -> ContactService:
    return ContactService(session=db_session, contacts=contact_repository)


def _user(session: Session, email: str) -> User:
    user = User(name="Someone", email=email, hashed_password="not a real hash")
    session.add(user)
    session.flush()

    return user


class Business:
    def __init__(self, session: Session, workspaces: WorkspaceService, slug: str):
        self.owner = _user(session, f"owner-{slug}@example.com")
        self.workspace = workspaces.create(
            WorkspaceCreate(name=slug.title(), slug=slug),
            creator=self.owner,
        )
        self.access = workspaces.access(self.workspace.id, self.owner)


@pytest.fixture
def acme(db_session: Session, workspaces: WorkspaceService) -> Business:
    return Business(db_session, workspaces, "acme-fashion")


@pytest.fixture
def rival(db_session: Session, workspaces: WorkspaceService) -> Business:
    return Business(db_session, workspaces, "rival-store")


def _payload(phone: str = NUMBER, **overrides: object) -> ContactCreate:
    return ContactCreate(phone_number=phone, **overrides)  # type: ignore[arg-type]


# --- creating ---------------------------------------------------------------


def test_a_contact_belongs_to_the_workspace_it_was_created_in(
    service: ContactService,
    acme: Business,
) -> None:
    contact = service.create(acme.access, _payload())

    assert contact.workspace_id == acme.workspace.id


def test_a_new_contact_is_a_lead(
    service: ContactService,
    acme: Business,
) -> None:
    assert service.create(acme.access, _payload()).status == ContactStatus.LEAD


def test_the_number_is_stored_normalised(
    service: ContactService,
    acme: Business,
) -> None:
    contact = service.create(acme.access, _payload("+92 300 1234567"))

    assert contact.phone_number == NUMBER


def test_a_duplicate_number_in_one_workspace_is_refused(
    service: ContactService,
    acme: Business,
) -> None:
    service.create(acme.access, _payload())

    with pytest.raises(ContactAlreadyExistsError):
        service.create(acme.access, _payload())


def test_a_number_written_differently_is_still_a_duplicate(
    service: ContactService,
    acme: Business,
) -> None:
    # The point of normalising: the same person typed two ways must not
    # become two contacts with two separate histories.
    service.create(acme.access, _payload(NUMBER))

    with pytest.raises(ContactAlreadyExistsError):
        service.create(acme.access, _payload("0092 300 123 4567"))


def test_two_businesses_can_each_have_the_same_customer(
    service: ContactService,
    acme: Business,
    rival: Business,
) -> None:
    # The rule the plan states outright: a phone number is not globally
    # unique, because one person can buy from two shops.
    mine = service.create(acme.access, _payload())
    theirs = service.create(rival.access, _payload())

    assert mine.id != theirs.id
    assert mine.phone_number == theirs.phone_number == NUMBER


def test_everything_but_the_number_is_optional(
    service: ContactService,
    acme: Business,
) -> None:
    contact = service.create(acme.access, _payload())

    assert contact.name is None
    assert contact.email is None
    assert contact.source is None
    assert contact.external_id is None
    assert contact.meta == {}


def test_what_the_business_knows_is_kept(
    service: ContactService,
    acme: Business,
) -> None:
    contact = service.create(
        acme.access,
        ContactCreate(
            phone_number=NUMBER,
            name="Ayesha",
            email="ayesha@example.com",
            status=ContactStatus.CUSTOMER,
            source="whatsapp",
            external_id="shopify-4471",
            metadata={"size": "M"},
        ),
    )

    assert contact.name == "Ayesha"
    assert contact.status == ContactStatus.CUSTOMER
    assert contact.source == "whatsapp"
    assert contact.external_id == "shopify-4471"
    assert contact.meta == {"size": "M"}


# --- reading ----------------------------------------------------------------


def test_a_contact_is_readable_from_its_own_workspace(
    service: ContactService,
    acme: Business,
) -> None:
    created = service.create(acme.access, _payload())

    assert service.get(acme.access, created.id).id == created.id


def test_another_business_cannot_read_your_contact(
    service: ContactService,
    acme: Business,
    rival: Business,
) -> None:
    created = service.create(acme.access, _payload())

    with pytest.raises(ContactNotFoundError):
        service.get(rival.access, created.id)


def test_a_contact_that_never_existed_fails_the_same_way(
    service: ContactService,
    acme: Business,
    rival: Business,
) -> None:
    created = service.create(acme.access, _payload())

    with pytest.raises(ContactNotFoundError) as somebody_elses:
        service.get(rival.access, created.id)

    with pytest.raises(ContactNotFoundError) as imaginary:
        service.get(rival.access, uuid.uuid4())

    assert somebody_elses.value.detail == imaginary.value.detail


def test_listing_never_crosses_into_another_business(
    service: ContactService,
    acme: Business,
    rival: Business,
) -> None:
    mine = service.create(acme.access, _payload())
    service.create(rival.access, _payload(OTHER_NUMBER))

    contacts, total = service.list_for(acme.access)

    assert [contact.id for contact in contacts] == [mine.id]
    assert total == 1


def test_listing_is_paginated(service: ContactService, acme: Business) -> None:
    for index in range(5):
        service.create(acme.access, _payload(f"+92300123456{index}"))

    first, total = service.list_for(acme.access, page=1, page_size=2)
    second, _ = service.list_for(acme.access, page=2, page_size=2)

    assert len(first) == len(second) == 2
    assert total == 5
    assert not {c.id for c in first} & {c.id for c in second}


def test_pages_are_stable_between_identical_requests(
    service: ContactService,
    acme: Business,
) -> None:
    # Every row here shares one created_at, so without the id as a
    # tiebreak the two pages could overlap.
    for index in range(5):
        service.create(acme.access, _payload(f"+92300123456{index}"))

    first, _ = service.list_for(acme.access, page=1, page_size=2)
    again, _ = service.list_for(acme.access, page=1, page_size=2)

    assert [c.id for c in first] == [c.id for c in again]


# --- filtering --------------------------------------------------------------


def test_contacts_can_be_filtered_by_status(
    service: ContactService,
    acme: Business,
) -> None:
    service.create(acme.access, _payload(NUMBER, status=ContactStatus.CUSTOMER))
    service.create(acme.access, _payload(OTHER_NUMBER))

    contacts, total = service.list_for(acme.access, status=ContactStatus.CUSTOMER)

    assert total == 1
    assert contacts[0].phone_number == NUMBER


def test_contacts_can_be_filtered_by_source(
    service: ContactService,
    acme: Business,
) -> None:
    service.create(acme.access, _payload(NUMBER, source="whatsapp"))
    service.create(acme.access, _payload(OTHER_NUMBER, source="manual"))

    contacts, total = service.list_for(acme.access, source="whatsapp")

    assert total == 1
    assert contacts[0].source == "whatsapp"


@pytest.mark.parametrize("term", ["ayesha", "AYESHA", "yesh"])
def test_search_finds_a_name_whatever_the_case(
    service: ContactService,
    acme: Business,
    term: str,
) -> None:
    service.create(acme.access, _payload(NUMBER, name="Ayesha"))
    service.create(acme.access, _payload(OTHER_NUMBER, name="Bilal"))

    contacts, total = service.list_for(acme.access, search=term)

    assert total == 1
    assert contacts[0].name == "Ayesha"


def test_search_also_matches_a_number_or_an_address(
    service: ContactService,
    acme: Business,
) -> None:
    service.create(
        acme.access,
        _payload(NUMBER, name="Ayesha", email="ayesha@example.com"),
    )
    service.create(acme.access, _payload(OTHER_NUMBER, name="Bilal"))

    assert service.list_for(acme.access, search="9876")[1] == 1
    assert service.list_for(acme.access, search="ayesha@")[1] == 1


def test_search_does_not_reach_another_business(
    service: ContactService,
    acme: Business,
    rival: Business,
) -> None:
    service.create(rival.access, _payload(NUMBER, name="Ayesha"))

    assert service.list_for(acme.access, search="Ayesha")[1] == 0


def test_the_total_counts_the_filter_not_the_workspace(
    service: ContactService,
    acme: Business,
) -> None:
    # A page and a total that disagree is a pagination control promising
    # a page that turns out to be empty.
    service.create(acme.access, _payload(NUMBER, name="Ayesha"))
    service.create(acme.access, _payload(OTHER_NUMBER, name="Bilal"))

    contacts, total = service.list_for(acme.access, search="Ayesha")

    assert len(contacts) == total == 1


# --- updating ---------------------------------------------------------------


def test_an_update_changes_only_what_was_sent(
    service: ContactService,
    acme: Business,
) -> None:
    created = service.create(acme.access, _payload(NUMBER, name="Ayesha"))

    updated = service.update(
        acme.access,
        created.id,
        ContactUpdate(status=ContactStatus.CUSTOMER),
    )

    assert updated.status == ContactStatus.CUSTOMER
    assert updated.name == "Ayesha"
    assert updated.phone_number == NUMBER


def test_a_number_can_be_changed_and_is_normalised(
    service: ContactService,
    acme: Business,
) -> None:
    created = service.create(acme.access, _payload())

    updated = service.update(
        acme.access,
        created.id,
        ContactUpdate(phone_number="0092 300 987 6543"),
    )

    assert updated.phone_number == OTHER_NUMBER


def test_a_number_cannot_be_moved_onto_another_contact(
    service: ContactService,
    acme: Business,
) -> None:
    service.create(acme.access, _payload(NUMBER))
    second = service.create(acme.access, _payload(OTHER_NUMBER))

    with pytest.raises(ContactAlreadyExistsError):
        service.update(acme.access, second.id, ContactUpdate(phone_number=NUMBER))


def test_setting_a_number_to_the_one_already_held_is_allowed(
    service: ContactService,
    acme: Business,
) -> None:
    created = service.create(acme.access, _payload())

    updated = service.update(
        acme.access, created.id, ContactUpdate(phone_number=NUMBER)
    )

    assert updated.phone_number == NUMBER


def test_another_business_cannot_update_your_contact(
    service: ContactService,
    acme: Business,
    rival: Business,
) -> None:
    created = service.create(acme.access, _payload(NUMBER, name="Ayesha"))

    with pytest.raises(ContactNotFoundError):
        service.update(rival.access, created.id, ContactUpdate(name="Taken Over"))

    assert service.get(acme.access, created.id).name == "Ayesha"
