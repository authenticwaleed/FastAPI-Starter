from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.core.phone import normalise_phone_number
from app.models.contact import ContactStatus

# Normalised on the way in, so that a number typed with spaces in the
# dashboard and the same number arriving from WhatsApp are one contact.
PhoneNumber = Annotated[str, AfterValidator(normalise_phone_number)]

Name = Annotated[str, Field(min_length=1, max_length=150)]
ExternalId = Annotated[str, Field(min_length=1, max_length=255)]
Source = Annotated[str, Field(min_length=1, max_length=50)]


class ContactCreate(BaseModel):
    """Request body for adding a contact by hand.

    Only the phone number is required. This is a product that reaches
    people on WhatsApp, so a contact without one is a row nothing can act
    on; everything else is what the business happens to know so far.
    """

    phone_number: PhoneNumber
    name: Name | None = None
    email: Annotated[EmailStr, Field(max_length=320)] | None = None
    status: ContactStatus = ContactStatus.LEAD
    source: Source | None = None
    external_id: ExternalId | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactUpdate(BaseModel):
    """A partial update. An omitted field means "leave this alone".

    The phone number can be changed, because people do change numbers,
    but it stays unique within the workspace: moving a contact onto an
    address another contact already holds is a merge, and a merge is a
    different operation than an edit.
    """

    phone_number: PhoneNumber | None = None
    name: Name | None = None
    email: Annotated[EmailStr, Field(max_length=320)] | None = None
    status: ContactStatus | None = None
    source: Source | None = None
    external_id: ExternalId | None = None
    metadata: dict[str, Any] | None = None


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phone_number: str
    name: str | None
    email: EmailStr | None
    status: ContactStatus
    source: str | None
    external_id: str | None
    # Reads the model's `meta` attribute, which carries the column the
    # plan calls `metadata`: the name is taken on a declarative class.
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime
    updated_at: datetime


class ContactPage(BaseModel):
    """One page of a workspace's contacts, with the total behind it."""

    items: list[ContactRead]
    total: int
    page: int
    page_size: int
