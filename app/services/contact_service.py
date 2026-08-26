import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ContactAlreadyExistsError,
    ContactNotFoundError,
)
from app.db.session import SessionDep
from app.models.contact import Contact, ContactStatus
from app.repositories.contact_repository import ContactRepository
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.workspace_service import WorkspaceAccess


class ContactService:
    """A workspace's end customers.

    Every method takes the WorkspaceAccess a dependency already resolved
    and passes its workspace id down to the repository. Nothing here
    accepts a bare workspace id, so there is no way to call this service
    for a workspace whose membership was never checked.
    """

    def __init__(self, session: Session, contacts: ContactRepository) -> None:
        self._session = session
        self._contacts = contacts

    def create(self, access: WorkspaceAccess, payload: ContactCreate) -> Contact:
        workspace_id = access.workspace.id

        if (
            self._contacts.get_by_phone_number(workspace_id, payload.phone_number)
            is not None
        ):
            raise ContactAlreadyExistsError(workspace_id, payload.phone_number)

        try:
            contact = self._contacts.create(
                workspace_id=workspace_id,
                phone_number=payload.phone_number,
                name=payload.name,
                email=payload.email,
                status=payload.status,
                source=payload.source,
                external_id=payload.external_id,
                meta=payload.metadata,
            )
            self._session.commit()
        except IntegrityError as exc:
            # Two requests can both pass the check above, and a WhatsApp
            # webhook will one day race the dashboard for the same person.
            # The unique index is what actually settles it.
            self._session.rollback()
            raise ContactAlreadyExistsError(workspace_id, payload.phone_number) from exc

        return contact

    def get(self, access: WorkspaceAccess, contact_id: uuid.UUID) -> Contact:
        contact = self._contacts.get(access.workspace.id, contact_id)

        if contact is None:
            raise ContactNotFoundError(access.workspace.id, contact_id)

        return contact

    def list_for(
        self,
        access: WorkspaceAccess,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: ContactStatus | None = None,
        source: str | None = None,
    ) -> tuple[Sequence[Contact], int]:
        workspace_id = access.workspace.id

        contacts = self._contacts.list_for_workspace(
            workspace_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            search=search,
            status=status,
            source=source,
        )
        total = self._contacts.count_for_workspace(
            workspace_id,
            search=search,
            status=status,
            source=source,
        )

        return contacts, total

    def update(
        self,
        access: WorkspaceAccess,
        contact_id: uuid.UUID,
        payload: ContactUpdate,
    ) -> Contact:
        contact = self.get(access, contact_id)
        workspace_id = access.workspace.id
        # Read before anything is mutated, so it survives the rollback
        # below without needing the row reloaded.
        current_number = contact.phone_number

        if payload.phone_number is not None and payload.phone_number != current_number:
            clash = self._contacts.get_by_phone_number(
                workspace_id,
                payload.phone_number,
            )

            if clash is not None:
                raise ContactAlreadyExistsError(workspace_id, payload.phone_number)

        try:
            self._contacts.update(
                contact,
                phone_number=payload.phone_number,
                name=payload.name,
                email=payload.email,
                status=payload.status,
                source=payload.source,
                external_id=payload.external_id,
                meta=payload.metadata,
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ContactAlreadyExistsError(
                workspace_id,
                payload.phone_number or current_number,
            ) from exc

        return contact


def get_contact_repository(session: SessionDep) -> ContactRepository:
    return ContactRepository(session)


ContactRepositoryDep = Annotated[ContactRepository, Depends(get_contact_repository)]


def get_contact_service(
    session: SessionDep,
    contacts: ContactRepositoryDep,
) -> ContactService:
    return ContactService(session=session, contacts=contacts)


ContactServiceDep = Annotated[ContactService, Depends(get_contact_service)]
