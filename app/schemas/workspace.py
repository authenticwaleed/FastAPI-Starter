from datetime import datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.workspace import WorkspaceStatus


def _a_real_timezone(value: str) -> str:
    """Reject a timezone the standard library has never heard of.

    Worth doing at the edge rather than storing whatever arrives: every
    business-hours rule and every analytics bucket is reported in this
    zone, so a typo here is wrong numbers on a dashboard months later
    rather than an error anyone can trace back.
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown timezone: {value!r}") from None

    return value


def _an_iso_currency_code(value: str) -> str:
    code = value.upper()

    if not code.isalpha() or len(code) != 3:
        raise ValueError("must be a three-letter ISO 4217 code, such as USD")

    return code


Name = Annotated[str, Field(min_length=1, max_length=100)]

# Lowercase words joined by single hyphens: what belongs in a URL, and
# nothing that needs escaping to get there.
Slug = Annotated[
    str,
    Field(min_length=3, max_length=63, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]

Timezone = Annotated[str, Field(max_length=64), AfterValidator(_a_real_timezone)]

Currency = Annotated[str, AfterValidator(_an_iso_currency_code)]


class WorkspaceCreate(BaseModel):
    name: Name
    slug: Slug
    timezone: Timezone = "UTC"
    default_currency: Currency = "USD"


class WorkspaceUpdate(BaseModel):
    """A partial update. An omitted field means "leave this alone".

    `slug` is absent on purpose. It is a public identifier that ends up in
    URLs and in customers' bookmarks, so changing it breaks links that
    already exist. Moving a workspace to a new slug should be a deliberate
    operation with a redirect behind it, not a field in a PATCH.
    """

    name: Name | None = None
    timezone: Timezone | None = None
    default_currency: Currency | None = None


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    status: WorkspaceStatus
    timezone: str
    default_currency: str
    created_at: datetime
    updated_at: datetime


class WorkspacePage(BaseModel):
    """One page of the caller's workspaces, plus how many they have."""

    items: list[WorkspaceRead]
    total: int
    page: int
    page_size: int
