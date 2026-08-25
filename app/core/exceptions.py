class AppError(Exception):
    """Base class for the errors this application raises on purpose.

    Every one of these carries two messages. `detail` is what the client is
    told; the exception's own `str()` is for logs and may carry context that
    must not leave the process, such as which address was already taken.

    Nothing here mentions HTTP. Turning these into status codes is the API
    layer's job, in `app/api/errors.py`, which is the whole point of the
    split: a service can raise the right error without knowing that a 409
    exists.
    """

    detail = "Something went wrong"

    def __init__(self, message: str = "", *, detail: str | None = None) -> None:
        # An instance may override the class-wide public message when the
        # same error means something more specific to the caller.
        if detail is not None:
            self.detail = detail

        super().__init__(message or self.detail)


class UserNotFoundError(AppError):
    """No user exists with the requested id."""

    detail = "User not found"

    def __init__(self, user_id: int) -> None:
        super().__init__(f"User not found: {user_id}")
        self.user_id = user_id


class EmailAlreadyExistsError(AppError):
    """The email address is already registered to someone."""

    detail = "Email already registered"

    def __init__(self, email: str) -> None:
        # The address belongs in the log line, not in the response.
        super().__init__(f"Email already registered: {email}")
        self.email = email


class InvalidCredentialsError(AppError):
    """Authentication failed.

    Covers a wrong password, an unknown address and a token that does not
    hold up, on purpose: separating those would tell an attacker which
    accounts exist.
    """

    detail = "Incorrect email or password"


class InactiveUserError(AppError):
    """The credentials were right, but the account is deactivated."""

    detail = "Inactive user"

    def __init__(self, user_id: int) -> None:
        super().__init__(f"User is not active: {user_id}")
        self.user_id = user_id


class IncorrectPasswordError(AppError):
    """A password change was attempted without the current password.

    Separate from InvalidCredentialsError on purpose. The bearer token is
    valid and the caller is who they claim to be, so a 401 would tell the
    client its session had expired and send a perfectly good one back to
    the login screen. What failed is one field of the request.
    """

    detail = "Current password is incorrect"

    def __init__(self, user_id: int) -> None:
        super().__init__(f"Incorrect current password for user: {user_id}")
        self.user_id = user_id
