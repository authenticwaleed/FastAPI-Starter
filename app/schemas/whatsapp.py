from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.phone import normalise_phone_number
from app.models.whatsapp_account import (
    MessagingProviderName,
    WhatsAppAccountStatus,
)

PhoneNumber = Annotated[str, AfterValidator(normalise_phone_number)]
ExternalId = Annotated[str, Field(min_length=1, max_length=64)]


class WhatsAppConnect(BaseModel):
    """Credentials for the workspace's WhatsApp Business number.

    The access token appears here and nowhere else. It is encrypted before
    it is stored, never returned by any response, and never formatted into
    a log line.
    """

    phone_number: PhoneNumber
    external_phone_number_id: ExternalId
    access_token: Annotated[str, Field(min_length=1, max_length=1024)]
    external_business_account_id: ExternalId | None = None
    provider: MessagingProviderName = MessagingProviderName.META_CLOUD


class WhatsAppAccountRead(BaseModel):
    """The connection, as anybody is ever allowed to see it.

    There is no token field of any kind, encrypted or otherwise, which is
    the same guarantee UserRead makes about passwords: a value that is not
    in the schema cannot be serialised into a response by accident.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: MessagingProviderName
    phone_number: str
    external_phone_number_id: str
    external_business_account_id: str | None
    status: WhatsAppAccountStatus
    connected_at: datetime
    created_at: datetime
    updated_at: datetime
