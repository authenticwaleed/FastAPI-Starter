from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """Credentials submitted to `/auth/login`.

    Deliberately without the length limits `UserCreate` applies. Login only
    compares the value against a stored hash, and rejecting a wrong password
    with 422 rather than 401 would leak the password policy and tell an
    attacker their guess was never even checked.
    """

    email: EmailStr
    password: str


class Token(BaseModel):
    """The bearer token returned by `/auth/login`."""

    access_token: str

    # Named and valued to match the header the client sends back:
    # `Authorization: Bearer <access_token>`.
    token_type: str = "bearer"  # noqa: S105  (a scheme name, not a secret)
