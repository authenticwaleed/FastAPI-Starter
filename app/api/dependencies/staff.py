"""The platform door, declared in a route's signature.

The same shape as `app/api/dependencies/workspace.py`, deliberately, so
that the two surfaces read alike even though they are about opposite
things. A route that says `StaffAdminDep` has said what it needs in the
place a reviewer looks first, and it is in the generated OpenAPI rather
than in an `if` somebody can leave out.

What it does not do is enforce. The service checks the same rank again,
because a service is also called by other things -- on this surface, a
command line -- and none of those pass through a route. This is the
declaration; `StaffService` is the enforcement.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.api.dependencies.auth import AuthenticatedDep
from app.core.config import get_settings
from app.core.exceptions import (
    AddressNotAllowedError,
    InsufficientStaffRoleError,
)
from app.models.staff_member import StaffRole, permits
from app.services.staff_service import (
    MAY_ADMINISTER,
    MAY_GRANT,
    StaffActor,
    StaffServiceDep,
)

# What the user_agent column holds. Trimmed rather than refused, like the
# session list's: a truncated label still says "Firefox on a Mac", where
# a rejected request says nothing at all and loses the audit entry too.
_USER_AGENT_LIMIT = 255


def get_staff_actor(
    request: Request,
    authenticated: AuthenticatedDep,
    service: StaffServiceDep,
) -> StaffActor:
    """Turn the bearer token into proved platform access.

    Depends on the whole `Authenticated` rather than just the user,
    because the session is half the check: this surface refuses one that
    has been left idle, which is what "staff do not reuse ordinary
    sessions" comes to in practice.

    The address and user agent are read here and carried on the actor,
    because every act on this surface is logged with them and a service
    that had to be handed a Request would be a service that could only be
    called by a route.
    """
    address = request.client.host if request.client else None

    _from_an_allowed_address(address)

    return service.access(
        authenticated.user,
        authenticated.session,
        ip_address=address,
        user_agent=_trimmed(request.headers.get("user-agent")),
    )


def _from_an_allowed_address(address: str | None) -> None:
    """Refuse the console from an address nobody put on the list.

    Off unless configured, and it has to be: a deployment shipping with
    an allowlist would lock its own operator out on the first day.

    Where it earns its place is a console reachable from the public
    internet, where an address is a second factor that costs nothing and
    cannot be phished. It is checked before the staff row is even looked
    up, so a stolen session on the wrong network learns nothing about
    whether the account it holds is staff.

    Exact addresses rather than ranges. A CIDR matcher here would be a
    small parser nobody tests against a range that matters, and a
    deployment that needs one has a firewall in front of this that is
    better at it.
    """
    allowed = get_settings().admin_ip_allowlist

    if not allowed:
        return

    if address is None or address not in allowed:
        raise AddressNotAllowedError(address)


# Any live staff member, whatever their rank: the check is being staff at
# all. Named as well as aliased so that a route saying `StaffDep` reads
# as a decision rather than as the absence of one.
StaffActorDep = Annotated[StaffActor, Depends(get_staff_actor)]
StaffDep = StaffActorDep


def require_staff_role(needed: StaffRole) -> Callable[[StaffActor], StaffActor]:
    """Build a dependency admitting this rank and everything above it.

    A ladder rather than a set of permitted roles, which is where this
    differs from `require_workspace_role`. The tenant roles fan out --
    an agent handles customers and an admin manages people, and neither
    contains the other -- while these three are cumulative by
    construction: everything support may do, an admin may do too.
    """

    def dependency(actor: StaffActorDep) -> StaffActor:
        if not permits(actor.role, needed):
            raise InsufficientStaffRoleError(actor.role, needed)

        return actor

    return dependency


StaffAdminDep = Annotated[StaffActor, Depends(require_staff_role(MAY_ADMINISTER))]

StaffOwnerDep = Annotated[StaffActor, Depends(require_staff_role(MAY_GRANT))]


def _trimmed(user_agent: str | None) -> str | None:
    return user_agent[:_USER_AGENT_LIMIT] if user_agent else None
