from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    """What to call a key, and how long it should last."""

    name: Annotated[str, Field(min_length=1, max_length=100)]
    # Null means it does not expire. Offered rather than imposed: a key
    # that stops working on a date nobody remembers choosing is an outage
    # in a customer's system, and the honest place for that decision is
    # the customer. Two years is the ceiling, which is long enough not to
    # be an obstacle and short enough that "forever" stays a deliberate
    # choice rather than a typo.
    expires_in_days: Annotated[int | None, Field(ge=1, le=730)] = None


class ApiKeyRead(BaseModel):
    """A key as it can be shown again: everything except the key.

    `key_prefix` is the readable fragment. It is what answers "which of
    these three is the one on the staging server", which a name chosen in
    a hurry six months ago does not.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """The one response that carries the key itself.

    Its own type rather than an optional field on the one above, so that
    the secret is in the schema of exactly one endpoint. A nullable `key`
    on every read would be a field somebody logs the whole of a response
    to inspect, on the reasonable assumption that it is usually null.
    """

    # Shown once. Nothing stored can reproduce it, so a client that does
    # not keep it has to make another key.
    key: str


class ApiKeyIdentity(BaseModel):
    """What a key says about itself, to whoever is holding it.

    The endpoint an integration calls first: it confirms the key works and
    says which workspace it addresses, so a misconfigured deployment fails
    at setup rather than by writing to the wrong business's inbox.
    """

    workspace_id: UUID
    name: str
    key_prefix: str
    expires_at: datetime | None
