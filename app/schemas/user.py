from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
    )
    email: EmailStr


class UserCreate(UserBase):
    """Request body for creating a user."""


class UserRead(UserBase):
    """User representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool = True
