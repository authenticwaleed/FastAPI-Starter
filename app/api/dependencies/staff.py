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
from app.core.exceptions import InsufficientStaffRoleError
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
    return service.access(
        authenticated.user,
        authenticated.session,
        ip_address=request.client.host if request.client else None,
        user_agent=_trimmed(request.headers.get("user-agent")),
    )


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
