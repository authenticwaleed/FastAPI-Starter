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
