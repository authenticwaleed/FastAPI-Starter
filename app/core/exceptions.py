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


class WorkspaceNotFoundError(AppError):
    """No workspace with that id is visible to this user.

    Deliberately the same error whether the workspace does not exist, has
    been cancelled, or belongs to somebody else. Distinguishing them would
    turn the id in the URL into a way of asking which businesses have
    accounts here, which is not a question a stranger gets to ask.
    """

    detail = "Workspace not found"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"Workspace not found or not accessible: {workspace_id}")
        self.workspace_id = workspace_id


class SlugAlreadyExistsError(AppError):
    """The workspace slug is taken.

    Cancelled workspaces keep their slug. It may already be in a customer's
    bookmarks or a public URL, and handing it to somebody else would let
    them inherit that.
    """

    detail = "Workspace slug already taken"

    def __init__(self, slug: str) -> None:
        super().__init__(f"Workspace slug already taken: {slug}")
        self.slug = slug


class InsufficientWorkspaceRoleError(AppError):
    """The user is a member, but their role does not permit this.

    A 403 rather than the 404 a stranger gets: this caller has already
    proved they belong here, so confirming the workspace exists tells them
    nothing they did not know.
    """

    detail = "Your role does not permit this action"

    def __init__(self, workspace_id: object, role: object) -> None:
        super().__init__(
            f"Role {role} may not perform this action in workspace {workspace_id}"
        )
        self.workspace_id = workspace_id
        self.role = role


class WorkspaceOwnershipError(AppError):
    """The account still solely owns a workspace.

    Deleting it would leave a business with no one able to administer it,
    so the owner has to hand it over first. There is nothing to hand it
    over with yet, which is the honest state of things until memberships
    can be managed.
    """

    detail = "Transfer or close your workspaces before deleting your account"

    def __init__(self, user_id: int, workspace_ids: list[object]) -> None:
        super().__init__(
            f"User {user_id} is the only owner of workspaces: {workspace_ids}"
        )
        self.user_id = user_id
        self.workspace_ids = workspace_ids


class MembershipNotFoundError(AppError):
    """That user is not a member of this workspace.

    Safe to distinguish from every other refusal, unlike the workspace
    errors above: whoever is asking has already proved they belong here,
    so being told who is and is not on their own team reveals nothing.
    """

    detail = "That user is not a member of this workspace"

    def __init__(self, workspace_id: object, user_id: int) -> None:
        super().__init__(f"User {user_id} is not a member of workspace {workspace_id}")
        self.workspace_id = workspace_id
        self.user_id = user_id


class LastOwnerError(AppError):
    """The workspace would be left with nobody able to administer it.

    Raised for the last owner being removed, demoted, or leaving. Every
    route into a workspace's settings requires an owner, so a workspace
    without one is a business its own members are locked out of, with no
    way back in that does not involve support.
    """

    detail = "A workspace must keep at least one owner"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"Workspace {workspace_id} would be left without an owner")
        self.workspace_id = workspace_id


class InvitationNotFoundError(AppError):
    """No usable invitation matches that token.

    Covers an unknown token, one whose workspace has since been closed,
    and one that was revoked. All three are the same answer for the same
    reason the workspace errors are: whoever is holding the link has not
    proved anything yet.
    """

    detail = "Invitation not found"


class InvitationExpiredError(AppError):
    """The invitation was real, and is no longer.

    Distinguished from "not found" on purpose. This is not a secret --
    the holder had a valid link -- and "your link expired, ask for
    another" is a different thing to tell somebody than "no such link".
    """

    detail = "This invitation has expired"


class InvitationAlreadyAcceptedError(AppError):
    """The invitation has been used.

    Acceptance is single-use: `accepted_at` is set once, inside the same
    transaction that creates the membership, so a link that arrives twice
    cannot produce a second one.
    """

    detail = "This invitation has already been accepted"


class InvitationNotYoursError(AppError):
    """The invitation names a different address than the account using it.

    An invitation is addressed to a person, and a forwarded link should
    not hand somebody else a seat in a workspace that was never offered
    to them.
    """

    detail = "This invitation was sent to a different email address"


class AlreadyAMemberError(AppError):
    """That person already belongs to this workspace."""

    detail = "That person is already a member of this workspace"

    def __init__(self, workspace_id: object, email: str) -> None:
        super().__init__(f"{email} is already a member of workspace {workspace_id}")
        self.workspace_id = workspace_id
        self.email = email


class PendingInvitationExistsError(AppError):
    """An invitation to that address is already outstanding.

    Sending a second would leave two live links to one seat, and revoking
    one of them would look like revoking access when it was not. Revoke
    the first, then invite again.
    """

    detail = "An invitation to that address is already outstanding"

    def __init__(self, workspace_id: object, email: str) -> None:
        super().__init__(f"{email} already has a pending invitation to {workspace_id}")
        self.workspace_id = workspace_id
        self.email = email
