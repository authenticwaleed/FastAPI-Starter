import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.contact import Contact, ContactStatus


class ContactRepository:
    """Every query against the contacts table lives here.

    Each method takes `workspace_id` as its first argument, without
    exception and including the lookups by primary key. A contact id is a
    UUID and unguessable, but "unguessable" is not an access control:
    ids leak through logs, exports and support tickets, and the moment one
    method is willing to answer without a workspace, the tenant boundary
    depends on every caller remembering to check.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        phone_number: str,
        name: str | None,
        email: str | None,
        status: ContactStatus,
        source: str | None,
        external_id: str | None,
        meta: dict[str, Any],
    ) -> Contact:
        contact = Contact(
            workspace_id=workspace_id,
            phone_number=phone_number,
            name=name,
            email=email,
            status=status,
            source=source,
            external_id=external_id,
            meta=meta,
        )

        self._session.add(contact)
        self._session.flush()

        return contact

    def get(self, workspace_id: uuid.UUID, contact_id: uuid.UUID) -> Contact | None:
        return self._session.scalar(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.workspace_id == workspace_id,
            )
        )

    def get_by_phone_number(
        self,
        workspace_id: uuid.UUID,
        phone_number: str,
    ) -> Contact | None:
        """The lookup the WhatsApp webhook will live on.

        Within one workspace a number identifies a person. Across
        workspaces it does not, which is why this is not a global lookup.
        """
        return self._session.scalar(
            select(Contact).where(
                Contact.workspace_id == workspace_id,
                Contact.phone_number == phone_number,
            )
        )

    def get_by_external_id(
        self,
        workspace_id: uuid.UUID,
        external_id: str,
    ) -> Contact | None:
        """The business's own id for this person, in whatever system.

        Unique per workspace, which is what lets a storefront sync re-run
        without duplicating anybody -- and what makes it a usable
        fallback when a customer record carries no phone number.
        """
        return self._session.scalar(
            select(Contact).where(
                Contact.workspace_id == workspace_id,
                Contact.external_id == external_id,
            )
        )

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        search: str | None = None,
        status: ContactStatus | None = None,
        source: str | None = None,
    ) -> Sequence[Contact]:
        return self._session.scalars(
            self._filtered(select(Contact), workspace_id, search, status, source)
            # Newest first, which is what a contacts screen wants, with the
            # id breaking ties so pages cannot overlap or skip.
            .order_by(Contact.created_at.desc(), Contact.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        search: str | None = None,
        status: ContactStatus | None = None,
        source: str | None = None,
    ) -> int:
        return (
            self._session.scalar(
                self._filtered(
                    select(func.count()).select_from(Contact),
                    workspace_id,
                    search,
                    status,
                    source,
                )
            )
            or 0
        )

    @staticmethod
    def _filtered(
        statement: Select[Any],
        workspace_id: uuid.UUID,
        search: str | None,
        status: ContactStatus | None,
        source: str | None,
    ) -> Select[Any]:
        """The filters, applied once to both the page and its count.

        Written in one place because a page and a total that disagree is
        the kind of bug that only shows up as a pagination control that
        promises a page which turns out to be empty.
        """
        criteria: list[ColumnElement[bool]] = [Contact.workspace_id == workspace_id]

        if status is not None:
            criteria.append(Contact.status == status)

        if source is not None:
            criteria.append(Contact.source == source)

        if search:
            # Whoever is searching has a name, a number or an address in
            # mind and does not want to say which. `ilike` because a
            # contacts search that is case-sensitive is a search that
            # looks broken.
            pattern = f"%{search}%"
            criteria.append(
                or_(
                    Contact.name.ilike(pattern),
                    Contact.phone_number.ilike(pattern),
                    Contact.email.ilike(pattern),
                )
            )

        return statement.where(*criteria)

    def update(
        self,
        contact: Contact,
        *,
        phone_number: str | None = None,
        name: str | None = None,
        email: str | None = None,
        status: ContactStatus | None = None,
        source: str | None = None,
        external_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Contact:
        """Apply the fields supplied and leave the rest alone.

        `None` means "no change" here even for the nullable columns, which
        makes clearing one impossible through this path. That is the
        trade a PATCH of this shape makes, and the alternative -- a
        sentinel for "really set it to null" -- is not worth its own
        vocabulary until somebody actually needs to blank a name.
        """
        if phone_number is not None:
            contact.phone_number = phone_number

        if name is not None:
            contact.name = name

        if email is not None:
            contact.email = email

        if status is not None:
            contact.status = status

        if source is not None:
            contact.source = source

        if external_id is not None:
            contact.external_id = external_id

        if meta is not None:
            contact.meta = meta

        self._session.flush()

        return contact
