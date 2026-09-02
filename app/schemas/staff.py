from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.models.staff_member import StaffRole


class StaffRead(BaseModel):
    """One person who runs this platform, or used to.

    Keyed by user id rather than by the staff row's own id, like the
    tenant member list and for the same reason: a client asking to change
    what somebody may do knows who they are, not which row records that
    they were promoted.

    `revoked_at` is here rather than filtered out because a revoked row
    is the useful half of this screen after an incident -- who used to
    have this, and when it was taken away.
    """

    user_id: int
    name: str
    email: EmailStr
    role: StaffRole
    # Who promoted them, as an id. Null for the first owner and only for
    # them: somebody has to be able to grant this before anybody holds
    # it, so that row is seeded from the command line.
    granted_by_user_id: int | None
    granted_at: datetime
    revoked_at: datetime | None


class StaffGrant(BaseModel):
    """Request body for giving an existing account platform access.

    An account id, and no name or password: staff are ordinary accounts
    that have been promoted, so somebody joining the team registers the
    way a customer does. There is no endpoint here that creates a user,
    which is what keeps one sign-in, one password reset and one session
    list for everybody.

    An id rather than an address, because every other route on this
    surface is keyed on the id and a client that can reach this one can
    already search for accounts. Granting the *first* owner is the case
    with no console to search from, and that one is a command line and
    does take an address.
    """

    user_id: int
    role: StaffRole


class StaffUpdate(BaseModel):
    """Request body for moving somebody up or down the ladder."""

    role: StaffRole
