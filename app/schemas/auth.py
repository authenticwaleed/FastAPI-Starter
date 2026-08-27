from typing import Annotated

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Credentials submitted to `/auth/login`.

    Deliberately without the length limits `UserCreate` applies. Login only
    compares the value against a stored hash, and rejecting a wrong password
    with 422 rather than 401 would leak the password policy and tell an
    attacker their guess was never even checked.
    """

    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    """The body of `/auth/refresh` and of `/auth/logout`.

    One schema for both, because it is one thing: the secret that stands
    for a session. Refreshing spends it and logging out destroys it, and
    neither needs to know anything else about the caller -- which is why
    logging out works from a client whose access token has already run
    out, when sending the request is exactly what matters.
    """

    # Unconstrained for the same reason `LoginRequest.password` is: it is
    # only ever hashed and looked up, and a 422 would say "that was not
    # even checked".
    refresh_token: str


class TokenPair(BaseModel):
    """What `/auth/login` and `/auth/refresh` return.

    Two tokens with two jobs. The access token is what every request
    carries; it is short-lived, so it is worth little to whoever steals
    it. The refresh token is what buys the next access token, is used
    exactly once, and is the thing to keep somewhere a script cannot
    read.
    """

    access_token: str
    refresh_token: str

    # Named and valued to match the header the client sends back:
    # `Authorization: Bearer <access_token>`.
    token_type: str = "bearer"  # noqa: S105  (a scheme name, not a secret)

    # Seconds the access token has left, so a client can schedule its
    # refresh instead of waiting for a 401 to tell it. Describes the
    # access token only: the refresh token's life is the session's, which
    # moves every time it is used and so is not a number that can be
    # given out in advance.
    expires_in: int = Field(description="Seconds until the access token expires")


class EmailRequest(BaseModel):
    """The body of `/auth/forgot-password` and `/auth/resend-verification`.

    One field, and one schema for both, because both ask the same thing:
    send whatever is appropriate to this address. Neither endpoint says
    whether anything was.
    """

    email: EmailStr


class VerifyEmailRequest(BaseModel):
    """The body of `/auth/verify-email`."""

    # In the body rather than the path, unlike an invitation token. A
    # path is what makes an invitation a link somebody can click, and it
    # is also what puts the token in every access log a proxy writes.
    # These links are followed by the dashboard, which can perfectly well
    # put the token in a request body, so there is no reason to pay that.
    token: str


class ResetPasswordRequest(BaseModel):
    """The body of `/auth/reset-password`."""

    token: str

    # The new password is request input the same way `UserCreate.password`
    # is, so it carries the same policy. Unlike a login attempt, a 422
    # here leaks nothing: whoever is holding this link is entitled to
    # know what the rules for the password they are setting are.
    new_password: Annotated[str, Field(min_length=8, max_length=128)]
