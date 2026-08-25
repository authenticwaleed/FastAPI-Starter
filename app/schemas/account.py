from typing import Annotated

from pydantic import BaseModel, EmailStr, Field


class AccountUpdate(BaseModel):
    """Request body for changing one's own name or email address.

    Deliberately without the password field `UserUpdate` carries. Changing a
    password means proving you know the current one, which is a different
    request with a different shape, at `POST /account/change-password`.
    """

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    email: Annotated[EmailStr, Field(max_length=320)] | None = None


class PasswordChange(BaseModel):
    """Request body for `POST /account/change-password`."""

    # Unconstrained, for the reason `LoginRequest.password` is: it is only
    # ever compared against a stored hash, and answering a wrong one with a
    # 422 would both leak the policy the account was created under and say
    # the guess was never actually checked.
    current_password: str

    # The new password is request input the same way `UserCreate.password`
    # is, so it carries the same policy.
    new_password: Annotated[str, Field(min_length=8, max_length=128)]
