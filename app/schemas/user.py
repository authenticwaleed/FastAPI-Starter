from datetime import datetime

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


class UserRead(UserBase):
    """User representation returned by the API.

    Deliberately has no password field of any kind, so neither the plain
    password nor its hash can be serialised into a response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
