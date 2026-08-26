"""Phase 5 acceptance: the queries, and the constraints beneath them."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.contact import ContactStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.contact_repository import ContactRepository

NUMBER = "+923001234567"
OTHER_NUMBER = "+923009876543"


@pytest.fixture
def acme(db_session: Session) -> Workspace:
    return _workspace(db_session, "acme-fashion")


@pytest.fixture
def rival(db_session: Session) -> Workspace:
    return _workspace(db_session, "rival-store")


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


def _add(
    repository: ContactRepository,
    workspace: Workspace,
    phone_number: str = NUMBER,
    **fields: object,
):
    return repository.create(
        workspace_id=workspace.id,
        phone_number=phone_number,
        name=fields.get("name"),  # type: ignore[arg-type]
        email=fields.get("email"),  # type: ignore[arg-type]
        status=fields.get("status", ContactStatus.LEAD),  # type: ignore[arg-type]
        source=fields.get("source"),  # type: ignore[arg-type]
        external_id=fields.get("external_id"),  # type: ignore[arg-type]
        meta=fields.get("meta", {}),  # type: ignore[arg-type]
    )


def test_a_number_is_unique_within_a_workspace(
    contact_repository: ContactRepository,
    acme: Workspace,
    db_session: Session,
) -> None:
    _add(contact_repository, acme)

    with pytest.raises(IntegrityError):
        _add(contact_repository, acme)
        db_session.flush()


def test_a_number_is_not_unique_across_workspaces(
    contact_repository: ContactRepository,
    acme: Workspace,
    rival: Workspace,
) -> None:
    # Stated by the plan, and enforced here rather than assumed: the same
    # person can buy from two shops.
    assert _add(contact_repository, acme).id != _add(contact_repository, rival).id


def test_an_external_id_is_unique_within_a_workspace(
    contact_repository: ContactRepository,
    acme: Workspace,
    db_session: Session,
) -> None:
    # What lets a Shopify sync re-run without duplicating anybody.
    _add(contact_repository, acme, NUMBER, external_id="shopify-1")

    with pytest.raises(IntegrityError):
        _add(contact_repository, acme, OTHER_NUMBER, external_id="shopify-1")
        db_session.flush()


def test_many_contacts_may_have_no_external_id(
    contact_repository: ContactRepository,
    acme: Workspace,
) -> None:
    # PostgreSQL treats NULLs as distinct, which is what stops the
    # constraint above from allowing exactly one contact without one.
    _add(contact_repository, acme, NUMBER)
    _add(contact_repository, acme, OTHER_NUMBER)

    assert contact_repository.count_for_workspace(acme.id) == 2


def test_a_lookup_by_id_is_scoped_to_the_workspace(
    contact_repository: ContactRepository,
    acme: Workspace,
    rival: Workspace,
) -> None:
    contact = _add(contact_repository, acme)

    assert contact_repository.get(acme.id, contact.id) is contact
    assert contact_repository.get(rival.id, contact.id) is None


def test_a_lookup_by_number_is_scoped_to_the_workspace(
    contact_repository: ContactRepository,
    acme: Workspace,
    rival: Workspace,
) -> None:
    # The lookup the WhatsApp webhook will live on.
    contact = _add(contact_repository, acme)

    assert contact_repository.get_by_phone_number(acme.id, NUMBER) is contact
    assert contact_repository.get_by_phone_number(rival.id, NUMBER) is None


def test_a_lookup_for_a_workspace_that_does_not_exist_finds_nothing(
    contact_repository: ContactRepository,
    acme: Workspace,
) -> None:
    contact = _add(contact_repository, acme)

    assert contact_repository.get(uuid.uuid4(), contact.id) is None


def test_deleting_a_workspace_takes_its_contacts_with_it(
    contact_repository: ContactRepository,
    acme: Workspace,
    db_session: Session,
) -> None:
    contact = _add(contact_repository, acme)
    contact_id = contact.id

    db_session.delete(acme)
    db_session.flush()
    db_session.expunge_all()

    assert contact_repository.get(acme.id, contact_id) is None


def test_the_page_and_the_count_apply_the_same_filters(
    contact_repository: ContactRepository,
    acme: Workspace,
) -> None:
    _add(contact_repository, acme, NUMBER, name="Ayesha")
    _add(contact_repository, acme, OTHER_NUMBER, name="Bilal")

    listed = contact_repository.list_for_workspace(
        acme.id, limit=20, offset=0, search="Ayesha"
    )
    counted = contact_repository.count_for_workspace(acme.id, search="Ayesha")

    assert len(listed) == counted == 1
