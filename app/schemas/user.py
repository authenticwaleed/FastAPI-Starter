from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
    )
    email: EmailStr = Field(max_length=320)


class UserCreate(UserBase):
    """Request body for creating a user.

    The plain password appears here and nowhere else: it is hashed before it
    reaches the database and never leaves the API in a response.
    """

    password: str = Field(
        min_length=8,
        max_length=128,
    )


class UserUpdate(BaseModel):
    """Request body for a partial update.

    Every field is optional, and an omitted field means "leave this alone".
    The constraints sit inside `Annotated` so they apply to the value itself
    rather than to the nullable union around it.
    """

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    email: Annotated[EmailStr, Field(max_length=320)] | None = None

    # Supplying this replaces the stored hash. As with UserCreate, the plain
    # password only ever exists as request input.
    password: Annotated[str, Field(min_length=8, max_length=128)] | None = None


class UserRead(UserBase):
    """User representation returned by the API.

    Deliberately has no password field of any kind, so neither the plain
    password nor its hash can be serialised into a response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    # Null until somebody follows the link sent to this address, and null
    # again if the address changes. Nothing is gated on it yet, so a
    # client reads it to nudge rather than to lock anything.
    email_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserPage(BaseModel):
    """One page of users plus the context needed to ask for the next one.

    `total` counts every user, not just this page, so a client can work out
    how many pages exist without a second request.
    """

    items: list[UserRead]
    total: int
    page: int
    page_size: int
