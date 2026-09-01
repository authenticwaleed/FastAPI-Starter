import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.api.dependencies.auth import CurrentUserDep
from app.core import context
from app.core.exceptions import InsufficientWorkspaceRoleError
from app.models.workspace_membership import WorkspaceRole
from app.services.workspace_service import (
    MAY_ADMINISTER,
    MAY_CLOSE,
    MAY_HANDLE_CUSTOMERS,
    WorkspaceAccess,
    WorkspaceServiceDep,
)


def get_workspace_access(
    workspace_id: uuid.UUID,
    user: CurrentUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceAccess:
    """Turn the workspace id in the path into proven access to it.

    Every route under `/workspaces/{workspace_id}` depends on this rather
    than on the raw id, so a handler is never holding an id it has not
    already established the caller may use. The tenant check happens once,
    in one place, before any handler body runs -- which is the only version
    of it that cannot be forgotten in a route added later.

    Also where the workspace joins the log context, and for the same
    reason: this is the one place every tenant-scoped request goes
    through, so binding here is what makes "which business was this" a
    field on every line the request writes rather than something each of
    them has to remember to say. Bound after the check, never before -- an
    id somebody guessed at is not a workspace.
    """
    access = service.access(workspace_id, user)
    context.bind(workspace_id=access.workspace.id)

    return access


WorkspaceAccessDep = Annotated[WorkspaceAccess, Depends(get_workspace_access)]


def require_workspace_role(
    *allowed: WorkspaceRole,
) -> Callable[[WorkspaceAccess], WorkspaceAccess]:
    """Build a dependency that admits only these roles.

    The alternative is an `if` at the top of each handler, and the trouble
    with that is not repetition but silence: a route written next month
    that forgets one looks exactly like a route that is deliberately open.
    Stated as a dependency the requirement is in the signature, in the
    generated OpenAPI, and impossible to leave out by omission.

    Note what this does *not* replace. The service checks the same thing
    again, because a service is also called by other services and, before
    long, by background jobs, none of which pass through a route. This is
    the declaration; the service is the enforcement.
    """
    permitted = frozenset(allowed)

    def dependency(access: WorkspaceAccessDep) -> WorkspaceAccess:
        if access.role not in permitted:
            raise InsufficientWorkspaceRoleError(access.workspace.id, access.role)

        return access

    return dependency


# Any active member, whatever their role: the check is membership itself.
WorkspaceMemberDep = WorkspaceAccessDep

WorkspaceAgentDep = Annotated[
    WorkspaceAccess,
    Depends(require_workspace_role(*MAY_HANDLE_CUSTOMERS)),
]

WorkspaceAdminDep = Annotated[
    WorkspaceAccess,
    Depends(require_workspace_role(*MAY_ADMINISTER)),
]

WorkspaceOwnerDep = Annotated[
    WorkspaceAccess,
    Depends(require_workspace_role(*MAY_CLOSE)),
]
